import json

import httpx

from service.config import Settings


class LLMUnavailable(Exception):
    """Модель не настроена или недоступна."""


class LLMInvalidOutput(Exception):
    """Ответ получен, но не является JSON-объектом."""


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return self.settings.llm_enabled

    def _post(self, payload: dict) -> httpx.Response:
        return httpx.post(
            f"{self.settings.llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.llm_api_key}"},
            json=payload,
            timeout=self.settings.llm_timeout,
        )

    def complete_json(self, system: str, user: str, max_tokens: int = 700) -> dict:
        if not self.enabled:
            raise LLMUnavailable("OPENAI_API_KEY не задан")
        payload = {
            "model": self.settings.llm_model,
            "temperature": self.settings.llm_temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            response = self._post(payload)
            if response.status_code == 400:
                payload.pop("response_format")
                response = self._post(payload)
        except httpx.HTTPError as exc:
            raise LLMUnavailable("сервис модели недоступен") from exc
        if response.status_code >= 400:
            raise LLMUnavailable(f"сервис модели вернул HTTP {response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable("неожиданная структура ответа сервиса модели") from exc
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMInvalidOutput("ответ модели не является JSON") from exc
        if not isinstance(parsed, dict):
            raise LLMInvalidOutput("ответ модели не является JSON-объектом")
        return parsed
