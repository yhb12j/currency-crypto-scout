"""Ответы на вопросы по сохранённым записям набора. Ответ допускается только со ссылками на записи."""

import json
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from service.llm import LLMClient, LLMInvalidOutput, LLMUnavailable
from service.planning.models import Confidence

CONTEXT_LIMIT = 200
BLOCKED = ("прогноз", "предскаж", "что купить", "выгодно купить", "куда вложить", "будет стоить", "на завтра")
WITHHELD = "Ответ не сформирован. Требуется ручная проверка."

PROMPT = """Роль: аналитик данных. Источник фактов — только записи набора ниже (JSON, поле id).
Внешние знания, прогнозы и инвестиционные рекомендации запрещены.
Если данных в записях недостаточно или вопрос неоднозначен — needs_review=true, confidence="low".
Ответ: только JSON-объект с ключами
answer — краткий ответ на русском с числами из записей,
used_record_ids — массив id записей, на которых основан ответ,
confidence — "high" | "medium" | "low",
needs_review — boolean,
reason — одно предложение с обоснованием."""


class AnswerContract(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    answer: str
    used_record_ids: list[int] = Field(max_length=CONTEXT_LIMIT)
    confidence: Confidence
    needs_review: bool
    reason: str = ""


@dataclass
class Answer:
    answer: str
    used_record_ids: list[int] = field(default_factory=list)
    confidence: str = "low"
    needs_review: bool = True
    reason: str = ""
    records_considered: int = 0
    llm_raw: dict | None = None
    llm_error: str | None = None

    def to_response(self) -> dict:
        data = asdict(self)
        data.pop("llm_raw")
        data.pop("llm_error")
        return data

    def to_record(self) -> dict:
        return {**asdict(self), "kind": "answer"}


def _withheld(reason: str, considered: int = 0, **extra) -> Answer:
    return Answer(WITHHELD, reason=reason, records_considered=considered, **extra)


class Analyst:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def answer(self, question: str, dataset: dict, records: list[dict]) -> Answer:
        text = question.strip()
        if any(marker in text.lower() for marker in BLOCKED):
            return _withheld("Вопрос требует прогноза или рекомендации.")
        if not records:
            return _withheld("В наборе нет записей.")
        rows = records[:CONTEXT_LIMIT]
        n = len(rows)
        if not self.llm.enabled:
            return _withheld("Языковая модель не настроена.", n, llm_error="OPENAI_API_KEY не задан")

        lines = [json.dumps({"id": r["id"], "created_at": r["created_at"], **r["record_json"]}, ensure_ascii=False)
                 for r in rows]
        context = f"Набор: {dataset['name']} ({dataset['source']}), записей: {n}.\n" + "\n".join(lines)
        try:
            raw = self.llm.complete_json(PROMPT, f"{context}\n\nВопрос: {text}", max_tokens=600)
        except LLMUnavailable as exc:
            return _withheld(f"Модель недоступна: {exc}.", n, llm_error=str(exc))
        except LLMInvalidOutput as exc:
            return _withheld("Ответ модели не соответствует контракту JSON.", n, llm_error=str(exc))
        try:
            contract = AnswerContract.model_validate(raw)
        except ValidationError:
            return _withheld("Ответ модели не соответствует контракту JSON.", n, llm_raw=raw)

        known = {r["id"] for r in rows}
        cited = list(dict.fromkeys(contract.used_record_ids))
        if contract.needs_review or contract.confidence == "low":
            return _withheld(f"Модель: {contract.reason.strip() or 'недостаточно данных'}", n, llm_raw=raw)
        if any(i not in known for i in cited):
            return _withheld("Ответ ссылается на отсутствующие записи.", n, llm_raw=raw)
        if not cited:
            return _withheld("Ответ не подтверждён записями набора.", n, llm_raw=raw)
        return Answer(contract.answer.strip(), cited, contract.confidence, False, contract.reason.strip(), n, raw)
