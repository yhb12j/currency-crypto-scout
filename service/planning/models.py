from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from service.providers import SOURCES, Call

Confidence = Literal["high", "medium", "low"]
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}

HOLD_STEPS = (
    "Разбор формулировки запроса.",
    "Автоматический сбор остановлен.",
    "Запрос передан на ручную проверку.",
)


class PlanContract(BaseModel):
    """Контракт ответа языковой модели для операции планирования."""

    model_config = ConfigDict(strict=True, extra="ignore")

    plan_steps: list[str] = Field(min_length=1, max_length=5)
    api_url: str
    fields_to_keep: list[str]
    confidence: Confidence
    needs_review: bool
    reason: str = ""


@dataclass
class Plan:
    source: str
    plan_steps: list[str]
    fields_to_keep: list[str]
    confidence: str
    needs_review: bool = False
    reason: str = ""
    hints: list[str] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    decided_by: str = "policy"
    llm_raw: dict | None = None
    llm_error: str | None = None

    @property
    def api_url(self) -> str:
        if not self.calls or self.source not in SOURCES:
            return ""
        return self.calls[0].url(SOURCES[self.source].base_url)

    def hold(self, reason: str, hints: list[str] | tuple[str, ...]) -> "Plan":
        self.needs_review = True
        self.confidence = "low"
        self.reason = reason
        self.hints = list(hints)[:3]
        self.plan_steps = list(HOLD_STEPS)
        self.fields_to_keep = []
        self.calls = []
        return self

    def to_response(self) -> dict:
        return {
            "plan_steps": self.plan_steps,
            "api_url": self.api_url,
            "fields_to_keep": self.fields_to_keep,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "reason": self.reason,
            "hints": self.hints,
            "source": SOURCES[self.source].title if self.source in SOURCES else "",
            "notes": self.notes,
            "decided_by": self.decided_by,
        }

    def to_record(self) -> dict:
        data = asdict(self)
        data["kind"] = "plan"
        data["api_url"] = self.api_url
        return data

    @classmethod
    def from_record(cls, data: dict) -> "Plan":
        names = set(cls.__dataclass_fields__)
        values = {k: v for k, v in data.items() if k in names}
        values["calls"] = [Call(**c) for c in data.get("calls") or []]
        return cls(**values)
