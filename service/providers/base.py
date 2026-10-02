from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class Call:
    """Один запрос к внешнему сервису."""

    provider: str
    endpoint: str
    params: dict
    meta: dict = field(default_factory=dict)

    def url(self, base: str) -> str:
        return f"{base}{self.endpoint}?{urlencode(self.params)}"


def http_get(service: str, url: str, params: dict, headers: dict, timeout: float):
    try:
        response = httpx.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError(f"{service}: превышено время ожидания ({timeout:.0f} с).", 504) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"{service}: сервис недоступен.") from exc
    if response.status_code == 429:
        raise ProviderError(f"{service}: превышен лимит запросов.", 502)
    if response.status_code >= 400:
        raise ProviderError(f"{service}: HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{service}: ответ не в формате JSON.") from exc


def rounded(value, digits: int):
    try:
        return None if value is None else round(float(value), digits)
    except (TypeError, ValueError):
        return None
