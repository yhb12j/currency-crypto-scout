import pytest

from service.planning.policy import evaluate
from service.planning.query import parse
from service.providers import COINGECKO, EXCHANGERATE, resolve_source
from tests.conftest import load_queries


@pytest.mark.parametrize("row", load_queries(), ids=lambda r: f"q{r['id']}")
def test_reference_queries(row):
    plan = evaluate(parse(row["query"]), resolve_source(row["source"]))
    assert plan.needs_review is row["expected_needs_review"]
    assert 1 <= len(plan.plan_steps) <= 5
    if plan.needs_review:
        assert plan.confidence == "low" and plan.reason and plan.hints and not plan.calls
    else:
        assert plan.confidence in {"high", "medium"} and plan.calls and plan.fields_to_keep


def test_reference_set_composition():
    rows = load_queries()
    assert len(rows) == 10
    assert sum(not r["expected_needs_review"] for r in rows) == 7


@pytest.mark.parametrize("query, source, fragment", [
    ("Собери курс биткоина в рублях", EXCHANGERATE, "exchangerate.host не содержит криптовалют"),
    ("Собери курсы доллара к рублю", COINGECKO, "CoinGecko не содержит котировок"),
    ("Собери биткоин", COINGECKO, "нет ограничений"),
    ("Собери историю bitcoin за 2 года", COINGECKO, "не более чем за 365"),
    ("Собери курс доллара к рублю за 7 дней", EXCHANGERATE, "за период недоступны"),
    ("Собери цены bitcoin в тенге", COINGECKO, "не котирует"),
    ("Собери топ-10 монет и сохрани поля: foo, bar", COINGECKO, "недоступны"),
    ("Собери курс доллара к рублю на дату 2099-01-01", EXCHANGERATE, "в будущем"),
    ("Собери топ-10 криптовалют за 30 дней", COINGECKO, "24 часа и 7 дней"),
])
def test_review_cases(query, source, fragment):
    plan = evaluate(parse(query), source)
    assert plan.needs_review is True
    assert fragment in plan.reason


def test_defaults_lower_confidence_and_are_reported():
    plan = evaluate(parse("Собери топ монет и сохрани поля: name, price"), COINGECKO)
    assert plan.needs_review is False
    assert plan.confidence == "medium"
    assert plan.fields_to_keep == ["name", "price", "currency"]
    assert any("топ-10" in note for note in plan.notes)


def test_fx_plan_uses_usd_source_and_cross_rate_meta():
    plan = evaluate(parse("Собери курсы доллара и евро к рублю на дату 2026-09-01"), EXCHANGERATE)
    call = plan.calls[0]
    assert call.endpoint == "/historical"
    assert call.params == {"date": "2026-09-01", "source": "USD", "currencies": "EUR,RUB"}
    assert call.meta == {"base": "RUB", "targets": ["USD", "EUR"]}
    assert "access_key" not in plan.api_url


def test_source_inferred_without_dataset():
    assert evaluate(parse("Собери цены ethereum в евро"), None).source == "coingecko"
    assert evaluate(parse("Собери курс юаня к рублю"), None).source == "exchangerate"
