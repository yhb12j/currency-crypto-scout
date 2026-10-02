from service.config import Settings
from service.planning import Plan
from service.providers import fetch


def collect(plan: Plan, settings: Settings) -> list[dict]:
    """Выполняет вызовы плана и оставляет в записях только поля fields_to_keep."""
    rows: list[dict] = []
    for call in plan.calls:
        rows.extend(fetch(call, settings))
    return [{name: row.get(name) for name in plan.fields_to_keep} for row in rows]
