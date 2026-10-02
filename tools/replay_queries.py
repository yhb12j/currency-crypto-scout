"""Прогон эталонных запросов tests_data/queries.jsonl через работающий сервис.

    python tools/replay_queries.py [--base-url URL] [--collect]
"""

import argparse
import json
import sys
from pathlib import Path

import httpx

QUERIES = Path(__file__).resolve().parents[1] / "tests_data" / "queries.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--collect", action="store_true", help="выполнить сбор для запросов без ручной проверки")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    api = httpx.Client(base_url=args.base_url, timeout=120)
    try:
        known = {(d["name"], d["source"]): d["dataset_id"] for d in api.get("/datasets").json()}
    except httpx.HTTPError:
        print(f"Сервис {args.base_url} недоступен")
        return 2

    rows = [json.loads(x) for x in QUERIES.read_text(encoding="utf-8").splitlines() if x.strip()]
    matched = 0
    print(f"{'#':>2} {'ожид.':<6} {'факт':<6} {'итог':<4} {'conf':<6} {'записей':>7}  причина")
    for row in rows:
        key = (row["dataset_name"], row["source"])
        if key not in known:
            known[key] = api.post("/datasets", json={"name": key[0], "source": key[1]}).json()["dataset_id"]
        plan = api.post("/ai/plan_and_collect", json={"query": row["query"], "dataset_id": known[key]}).json()
        ok = plan["needs_review"] is row["expected_needs_review"]
        matched += ok
        saved = "-"
        if args.collect and not plan["needs_review"]:
            result = api.post(f"/datasets/{known[key]}/collect", json={"query": row["query"]})
            saved = str(result.json().get("records_saved", 0)) if result.is_success else f"HTTP {result.status_code}"
        flag = lambda v: "review" if v else "auto"  # noqa: E731
        print(f"{row['id']:>2} {flag(row['expected_needs_review']):<6} {flag(plan['needs_review']):<6} "
              f"{'OK' if ok else 'FAIL':<4} {plan['confidence']:<6} {saved:>7}  {plan.get('reason', '')[:80]}")

    stats = api.get("/audit/summary").json()
    print(f"\nСовпадений: {matched}/{len(rows)}")
    print(f"audit_runs: {stats['total']} (ok {stats['ok']}, needs_review {stats['needs_review']}, error {stats['error']})")
    return 0 if matched == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
