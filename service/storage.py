import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,
    created_at  TEXT NOT NULL,
    name        TEXT NOT NULL,
    source      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    dataset_id  TEXT NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    record_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    query        TEXT NOT NULL,
    plan_json    TEXT,
    needs_review INTEGER NOT NULL CHECK (needs_review IN (0, 1)),
    error        TEXT
);
CREATE TABLE IF NOT EXISTS audit_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    action      TEXT NOT NULL,
    input       TEXT,
    output      TEXT,
    status      TEXT NOT NULL CHECK (status IN ('ok', 'needs_review', 'error')),
    error       TEXT,
    duration_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_records_dataset ON records(dataset_id, id DESC);
CREATE INDEX IF NOT EXISTS ix_agent_runs_query ON agent_runs(query, id DESC);
CREATE INDEX IF NOT EXISTS ix_audit_status ON audit_runs(status, id DESC);
"""


def now_iso(delta: timedelta = timedelta(0)) -> str:
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


class Storage:
    def __init__(self, path: Path, redact=lambda text: text):
        self.path = path
        self.redact = redact

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript(SCHEMA)

    def _json(self, value: Any) -> str:
        return self.redact(json.dumps(value, ensure_ascii=False, default=str))

    # datasets
    def create_dataset(self, name: str, source: str) -> str:
        dataset_id = str(uuid.uuid4())
        with self._db() as conn:
            conn.execute(
                "INSERT INTO datasets (id, created_at, name, source) VALUES (?, ?, ?, ?)",
                (dataset_id, now_iso(), name, source),
            )
        return dataset_id

    _DATASET_SQL = """
        SELECT d.id AS dataset_id, d.created_at, d.name, d.source,
               COUNT(r.id) AS records_count, MAX(r.created_at) AS last_collected_at
        FROM datasets d LEFT JOIN records r ON r.dataset_id = d.id
    """

    def datasets(self) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(self._DATASET_SQL + " GROUP BY d.id ORDER BY d.created_at DESC, d.rowid DESC")
            return [dict(row) for row in rows]

    def dataset(self, dataset_id: str) -> dict | None:
        with self._db() as conn:
            row = conn.execute(self._DATASET_SQL + " WHERE d.id = ? GROUP BY d.id", (dataset_id,)).fetchone()
        return dict(row) if row else None

    # records
    def add_records(self, dataset_id: str, items: list[dict]) -> int:
        stamp = now_iso()
        with self._db() as conn:
            conn.executemany(
                "INSERT INTO records (created_at, dataset_id, record_json) VALUES (?, ?, ?)",
                [(stamp, dataset_id, self._json(item)) for item in items],
            )
        return len(items)

    def records(self, dataset_id: str, limit: int) -> list[dict]:
        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT r.id, r.created_at, r.dataset_id, d.source, r.record_json
                FROM records r JOIN datasets d ON d.id = r.dataset_id
                WHERE r.dataset_id = ? ORDER BY r.id DESC LIMIT ?
                """,
                (dataset_id, limit),
            ).fetchall()
        return [{**dict(row), "record_json": json.loads(row["record_json"])} for row in rows]

    # agent runs
    def add_agent_run(self, query: str, plan: dict, needs_review: bool, error: str | None) -> int:
        with self._db() as conn:
            cursor = conn.execute(
                "INSERT INTO agent_runs (created_at, query, plan_json, needs_review, error) VALUES (?, ?, ?, ?, ?)",
                (now_iso(), query, self._json(plan), int(needs_review), error),
            )
            return int(cursor.lastrowid)

    def agent_runs(self, limit: int, needs_review: bool | None = None) -> list[dict]:
        where, params = "", []
        if needs_review is not None:
            where, params = "WHERE needs_review = ?", [int(needs_review)]
        with self._db() as conn:
            rows = conn.execute(
                f"SELECT id, created_at, query, plan_json, needs_review, error FROM agent_runs {where} "
                "ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [
            {**dict(row), "plan_json": json.loads(row["plan_json"] or "null"), "needs_review": bool(row["needs_review"])}
            for row in rows
        ]

    def recent_plan(self, query: str, source: str, max_age: timedelta) -> dict | None:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT plan_json FROM agent_runs WHERE query = ? AND created_at >= ? ORDER BY id DESC LIMIT 20",
                (query, now_iso(-max_age)),
            ).fetchall()
        for row in rows:
            plan = json.loads(row["plan_json"] or "{}")
            if plan.get("kind") == "plan" and plan.get("source") == source:
                return plan
        return None

    # audit
    def add_audit(self, action: str, payload: Any, output: Any, status: str, error: str | None, duration_ms: int) -> None:
        with self._db() as conn:
            conn.execute(
                "INSERT INTO audit_runs (created_at, action, input, output, status, error, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now_iso(), action, self._json(payload), self._json(output), status,
                 self.redact(error) if error else None, duration_ms),
            )

    def audit(self, limit: int, status: str | None = None, action: str | None = None) -> list[dict]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if action:
            clauses.append("action = ?")
            params.append(action)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db() as conn:
            rows = conn.execute(
                f"SELECT id, created_at, action, input, output, status, error, duration_ms FROM audit_runs {where} "
                "ORDER BY id DESC LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [
            {**dict(row), "input": json.loads(row["input"] or "null"), "output": json.loads(row["output"] or "null")}
            for row in rows
        ]

    def audit_stats(self) -> dict:
        with self._db() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM audit_runs GROUP BY status").fetchall()
        counts = {row["status"]: row["n"] for row in rows}
        return {"total": sum(counts.values()), **{k: counts.get(k, 0) for k in ("ok", "needs_review", "error")}}
