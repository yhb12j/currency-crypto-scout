"""Сводка по базе SQLite: объём таблиц, последние запуски аудита, запросы на ручной проверке.

    python tools/inspect_db.py [N]
"""

import sqlite3
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from service.config import get_settings  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    path = get_settings().database_path
    if not path.exists():
        print(f"{path}: файл не найден")
        return
    conn = sqlite3.connect(path)
    print(path)
    for table in ("datasets", "records", "agent_runs", "audit_runs"):
        print(f"  {table:<11} {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>6}")

    print(f"\naudit_runs, последние {limit}:")
    for row in conn.execute(
        "SELECT id, created_at, action, status, duration_ms, COALESCE(error, '') FROM audit_runs "
        "ORDER BY id DESC LIMIT ?", (limit,)
    ):
        print(f"  {row[0]:>5}  {row[1]}  {row[2]:<17} {row[3]:<12} {row[4]:>6} ms  {row[5][:80]}")

    print("\nagent_runs, needs_review = 1:")
    for row in conn.execute("SELECT id, query, error FROM agent_runs WHERE needs_review = 1 ORDER BY id DESC LIMIT 20"):
        print(f"  {row[0]:>5}  {row[1][:60]}  |  {row[2]}")


if __name__ == "__main__":
    main()
