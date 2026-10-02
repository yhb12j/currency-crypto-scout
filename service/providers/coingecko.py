from datetime import datetime, timezone

from service.config import Settings
from service.providers.base import Call, ProviderError, http_get, rounded

BASE_URL = "https://api.coingecko.com/api/v3"
TITLE = "CoinGecko"


class CoinGeckoProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _get(self, call: Call):
        headers = {"x-cg-demo-api-key": self.settings.coingecko_key} if self.settings.coingecko_key else {}
        return http_get(TITLE, f"{BASE_URL}{call.endpoint}", call.params, headers, self.settings.http_timeout)

    def fetch(self, call: Call) -> list[dict]:
        if call.endpoint == "/coins/markets":
            return self._markets(call)
        if call.endpoint.endswith("/market_chart"):
            return self._history(call)
        raise ProviderError(f"{TITLE}: неподдерживаемый метод {call.endpoint}.", 500)

    def _markets(self, call: Call) -> list[dict]:
        data = self._get(call)
        if not isinstance(data, list):
            raise ProviderError(f"{TITLE}: неожиданная структура ответа.")
        currency = call.params["vs_currency"].upper()
        return [
            {
                "rank": item.get("market_cap_rank"),
                "name": item.get("name") or "",
                "symbol": (item.get("symbol") or "").upper(),
                "price": item.get("current_price"),
                "currency": currency,
                "market_cap": item.get("market_cap"),
                "volume_24h": item.get("total_volume"),
                "change_24h": rounded(item.get("price_change_percentage_24h_in_currency"), 2),
                "change_7d": rounded(item.get("price_change_percentage_7d_in_currency"), 2),
                "updated_at": item.get("last_updated") or "",
            }
            for item in data
            if isinstance(item, dict)
        ]

    def _history(self, call: Call) -> list[dict]:
        data = self._get(call)
        prices = data.get("prices") if isinstance(data, dict) else None
        if not isinstance(prices, list):
            raise ProviderError(f"{TITLE}: неожиданная структура истории.")
        caps = {int(p[0]): p[1] for p in data.get("market_caps") or [] if len(p) == 2}
        volumes = {int(p[0]): p[1] for p in data.get("total_volumes") or [] if len(p) == 2}
        pattern = "%Y-%m-%d %H:00" if call.params.get("days") == "1" else "%Y-%m-%d"
        currency = call.params["vs_currency"].upper()
        by_label: dict[str, dict] = {}
        for point in prices:
            if not isinstance(point, list) or len(point) != 2:
                continue
            ts = int(point[0])
            label = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime(pattern)
            by_label[label] = {
                "date": label,
                "coin": call.meta.get("coin_name", ""),
                "currency": currency,
                "price": rounded(point[1], 6),
                "market_cap": rounded(caps.get(ts), 0),
                "volume": rounded(volumes.get(ts), 0),
            }
        return list(by_label.values())
