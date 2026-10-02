from datetime import datetime, timezone

from service.config import Settings
from service.providers.base import Call, ProviderError, http_get

BASE_URL = "https://api.exchangerate.host"
TITLE = "exchangerate.host"

ERRORS = {
    101: "ключ доступа отсутствует или недействителен",
    104: "исчерпан месячный лимит запросов",
    105: "метод недоступен на текущем тарифе",
    106: "нет данных на указанную дату",
    202: "неизвестный код валюты",
    302: "некорректная дата",
}


class ExchangeRateProvider:
    """Кросс-курсы считаются через USD: базовая валюта бесплатного тарифа фиксирована."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch(self, call: Call) -> list[dict]:
        if not self.settings.exchangerate_key:
            raise ProviderError(f"{TITLE}: не задан EXCHANGERATE_API_KEY.", 500)
        params = {**call.params, "access_key": self.settings.exchangerate_key}
        data = http_get(TITLE, f"{BASE_URL}{call.endpoint}", params, {}, self.settings.http_timeout)
        if not isinstance(data, dict):
            raise ProviderError(f"{TITLE}: неожиданная структура ответа.")
        if not data.get("success"):
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            reason = ERRORS.get(error.get("code"), error.get("type") or "неизвестная ошибка")
            raise ProviderError(f"{TITLE}: {reason}.")

        usd = {code[3:]: float(v) for code, v in (data.get("quotes") or {}).items() if isinstance(v, (int, float))}
        usd["USD"] = 1.0
        base, targets = call.meta["base"], call.meta["targets"]
        if not usd.get(base):
            raise ProviderError(f"{TITLE}: нет курса базовой валюты {base}.")
        stamp = data.get("date") or datetime.fromtimestamp(int(data.get("timestamp") or 0), tz=timezone.utc).strftime("%Y-%m-%d")
        return [
            {"date": stamp, "base": base, "currency": code, "rate": round(usd[base] / usd[code], 6)}
            for code in targets
            if usd.get(code)
        ]
