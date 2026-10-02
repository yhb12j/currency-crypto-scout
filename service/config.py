import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        value = default
    return min(high, max(low, value))


@dataclass(frozen=True)
class Settings:
    database_path: Path
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    llm_temperature: float
    llm_timeout: float
    exchangerate_key: str
    coingecko_key: str
    http_timeout: float

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def secrets(self) -> tuple[str, ...]:
        return tuple(s for s in (self.llm_api_key, self.exchangerate_key, self.coingecko_key) if len(s) >= 8)

    def redact(self, text: str) -> str:
        for secret in self.secrets:
            text = text.replace(secret, "***")
        return text


def get_settings() -> Settings:
    env = os.environ.get
    path = Path(env("DATABASE_PATH", "data/market.db"))
    if not path.is_absolute():
        path = ROOT / path
    return Settings(
        database_path=path,
        llm_api_key=env("OPENAI_API_KEY", "").strip(),
        llm_base_url=(env("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1").strip() or "").rstrip("/"),
        llm_model=env("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        llm_temperature=_float("LLM_TEMPERATURE", 0.2, 0.0, 1.0),
        llm_timeout=_float("LLM_TIMEOUT", 45, 5, 120),
        exchangerate_key=env("EXCHANGERATE_API_KEY", "").strip(),
        coingecko_key=env("COINGECKO_API_KEY", "").strip(),
        http_timeout=_float("HTTP_TIMEOUT", 20, 3, 60),
    )
