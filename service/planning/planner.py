"""Планирование сбора.

Политика качества формирует параметры вызова только из белого списка.
Языковая модель формулирует шаги и может только ужесточить решение.
"""

from datetime import datetime, timezone

from pydantic import ValidationError

from service.llm import LLMClient, LLMInvalidOutput, LLMUnavailable
from service.planning import catalog, policy
from service.planning.models import CONFIDENCE_RANK, Plan, PlanContract
from service.planning.query import parse
from service.providers import SOURCES, Source

PROMPT = """Роль: планировщик сбора публичных котировок. Дата: {today}.
Источники:
1. CoinGecko — криптовалюты.
   /coins/markets: топ монет или выбранные монеты; цена, капитализация, объём, изменение за 24 ч и 7 дн.
   Валюты котировки: usd, eur, rub, cny, gbp, jpy, try, aed, chf. Поля: {market}.
   /coins/{{id}}/market_chart: история одной монеты за 1–365 дней. Поля: {history}.
2. exchangerate.host — курсы фиатных валют на текущий момент или на одну дату начиная с 1999-01-01.
   Периоды недоступны. Поля: {fx}.
Источник набора: {source}.

Правила:
- корректный запрос: определены активы и есть ограничение (количество, период, дата, валюта котировки или поля) →
  needs_review=false, confidence high или medium;
- двусмысленный запрос: нет активов или ограничений («самое важное», «по рынку», «сделай вывод») →
  needs_review=true, confidence=low;
- невыполнимый запрос: закрытые или приватные данные, прогнозы, инвестиционные рекомендации,
  несоответствие источнику набора → needs_review=true, confidence=low.
Текущая дата — {today}; все даты не позже неё являются прошедшими. Проверку дат, периодов и лимитов
выполняет сервис: не отклонять запрос из-за даты.
Значения цен и курсов не указывать. Ключи доступа не указывать. Конвертация не требуется:
валюта котировки передаётся параметром.

Ответ: только JSON-объект с ключами
plan_steps — массив из 1–5 шагов на русском (при needs_review=true — 1–3 шага),
api_url — адрес вызова без ключа или "",
fields_to_keep — массив полей из перечисленных,
confidence — "high" | "medium" | "low",
needs_review — boolean,
reason — одно предложение с обоснованием решения."""


class Planner:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def _prompt(self, source: Source | None) -> str:
        return PROMPT.format(
            today=datetime.now(timezone.utc).date().isoformat(),
            market=", ".join(catalog.MARKET_FIELDS),
            history=", ".join(catalog.HISTORY_FIELDS),
            fx=", ".join(catalog.FX_FIELDS),
            source=source.title if source else "не задан",
        )

    def plan(self, query: str, source: Source | None) -> Plan:
        plan = policy.evaluate(parse(query), source)
        if not query.strip():
            return plan
        if not self.llm.enabled:
            plan.llm_error = "OPENAI_API_KEY не задан"
            return plan

        try:
            raw = self.llm.complete_json(self._prompt(source or SOURCES.get(plan.source)), query.strip())
        except LLMUnavailable as exc:
            plan.llm_error = str(exc)
            return plan
        except LLMInvalidOutput as exc:
            plan.llm_error = str(exc)
            plan.decided_by = "contract"
            return plan if plan.needs_review else plan.hold(
                "Ответ модели не соответствует контракту JSON.", policy.HINTS_VAGUE)

        plan.llm_raw = raw
        try:
            contract = PlanContract.model_validate(raw)
        except ValidationError as exc:
            fields = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]})) or "структура"
            plan.llm_error = f"нарушение контракта JSON: {fields}"
            plan.decided_by = "contract"
            return plan if plan.needs_review else plan.hold(
                f"Ответ модели не соответствует контракту JSON ({fields}).", policy.HINTS_VAGUE)

        if plan.needs_review:
            plan.decided_by = "policy+model" if contract.needs_review else "policy"
            return plan
        if contract.needs_review or contract.confidence == "low":
            plan.decided_by = "model"
            return plan.hold(f"Модель: {contract.reason.strip() or 'низкая уверенность'}", policy.HINTS_VAGUE)

        steps = [s.strip()[:200] for s in contract.plan_steps
                 if s.strip() and "сохран" not in s.lower()][:4]
        if steps:
            plan.plan_steps = [*steps, f"Сохранение полей: {', '.join(plan.fields_to_keep)}."]
        if CONFIDENCE_RANK[contract.confidence] < CONFIDENCE_RANK[plan.confidence]:
            plan.confidence = contract.confidence
        plan.decided_by = "policy+model"
        return plan
