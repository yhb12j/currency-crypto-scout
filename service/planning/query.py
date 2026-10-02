"""Извлечение признаков из текста запроса."""

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from service.planning import catalog

BASE_RE = re.compile(
    r"(?:\bк\b|\bв\b|относительно)\s+(рубл\w*|доллар\w*|евро|юан\w*|тенге|фунт\w*|иен\w*|йен\w*|"
    r"лир\w*|франк\w*|дирхам\w*|usd|eur|rub|cny)"
)
COUNT_RES = (re.compile(r"топ[\s-]*(\d+)"),
             re.compile(r"(\d+)\s+(?:крипт|монет|запис|позици|токен|актив)"),
             re.compile(r"первы\w*\s+(\d+)"))
FIELDS_RE = re.compile(r"пол[еяй]\w*\s*:?\s*(.+)$")


@dataclass
class QueryFeatures:
    text: str
    coins: list[tuple[str, str]] = field(default_factory=list)
    fiats: list[str] = field(default_factory=list)
    crypto: bool = False
    history: bool = False
    by_volume: bool = False
    count: int | None = None
    days: int | None = None
    on_date: date | None = None
    base: str | None = None
    fields: list[str] = field(default_factory=list)
    restricted: str | None = None
    vague: bool = False

    @property
    def empty(self) -> bool:
        return not self.text


def _ordered(table, text: str) -> list:
    hits = [(m.start(), item) for item in table if (m := re.search(item[-1], text))]
    return [item for _, item in sorted(hits, key=lambda h: h[0])]


def fiat_code(word: str) -> str | None:
    return next((code for code, pattern in catalog.FIATS if re.search(pattern, word)), None)


def _count(text: str) -> int | None:
    for pattern in COUNT_RES:
        if m := pattern.search(text):
            return int(m.group(1))
    return None


def _days(text: str) -> int | None:
    if m := re.search(r"(\d+)\s*(?:дн|день|дней|сут)", text):
        return int(m.group(1))
    if m := re.search(r"(\d+)\s*час", text):
        return max(1, math.ceil(int(m.group(1)) / 24))
    for pattern, unit in ((r"(\d+)\s*недел", 7), (r"(\d+)\s*месяц", 30), (r"(\d+)\s*(?:год|лет)", 365)):
        if m := re.search(pattern, text):
            return int(m.group(1)) * unit
    for pattern, value in ((r"сутки", 1), (r"неделю", 7), (r"месяц", 30), (r"\bгод\b", 365)):
        if re.search(r"за\s+(?:последн\w+\s+)?" + pattern, text):
            return value
    return None


def _date(text: str) -> date | None:
    try:
        if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if m := re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text):
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    if "вчера" in text:
        return datetime.now(timezone.utc).date() - timedelta(days=1)
    return None


def _fields(text: str) -> list[str]:
    m = FIELDS_RE.search(text)
    if not m:
        return []
    tokens = [t for t in re.split(r"[\s,;]+", m.group(1)) if re.fullmatch(r"[a-z_0-9]+", t)]
    return list(dict.fromkeys(tokens))


def parse(query: str) -> QueryFeatures:
    text = (query or "").strip().lower().replace("ё", "е")
    features = QueryFeatures(text=text)
    if not text:
        return features
    features.restricted = next((label for marker, label in catalog.RESTRICTED if marker in text), None)
    features.vague = any(marker in text for marker in catalog.VAGUE)
    features.coins = [(cid, name) for cid, name, _ in _ordered(catalog.COINS, text)]
    features.fiats = [code for code, _ in _ordered(catalog.FIATS, text)]
    features.crypto = bool(features.coins) or bool(re.search(catalog.CRYPTO_TERMS, text))
    features.count = _count(text)
    features.days = _days(text)
    features.on_date = _date(text)
    features.history = bool(re.search(catalog.HISTORY_TERMS, text)) or (
        bool(features.coins) and features.days is not None and features.days >= 2
    )
    features.by_volume = bool(re.search(catalog.VOLUME_TERMS, text))
    if m := BASE_RE.search(text):
        features.base = fiat_code(m.group(1))
    features.fields = _fields(text)
    return features
