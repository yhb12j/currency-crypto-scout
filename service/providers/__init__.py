from dataclasses import dataclass

from service.config import Settings
from service.providers import coingecko, exchangerate
from service.providers.base import Call, ProviderError


@dataclass(frozen=True)
class Source:
    code: str
    title: str
    base_url: str


COINGECKO = Source("coingecko", coingecko.TITLE, coingecko.BASE_URL)
EXCHANGERATE = Source("exchangerate", exchangerate.TITLE, exchangerate.BASE_URL)
SOURCES = {s.code: s for s in (COINGECKO, EXCHANGERATE)}


def resolve_source(value: str | None) -> Source | None:
    text = (value or "").strip().lower().replace(" ", "")
    for source in SOURCES.values():
        if source.code in text:
            return source
    return None


def fetch(call: Call, settings: Settings) -> list[dict]:
    if call.provider == COINGECKO.code:
        return coingecko.CoinGeckoProvider(settings).fetch(call)
    if call.provider == EXCHANGERATE.code:
        return exchangerate.ExchangeRateProvider(settings).fetch(call)
    raise ProviderError(f"Неизвестный источник: {call.provider}.", 500)


__all__ = ["Call", "ProviderError", "Source", "SOURCES", "COINGECKO", "EXCHANGERATE", "resolve_source", "fetch"]
