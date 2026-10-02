import json
import os
from pathlib import Path

import pytest

TMP = Path(__file__).resolve().parent / ".tmp"
os.environ["DATABASE_PATH"] = str(TMP / "test.db")
for name in ("OPENAI_API_KEY", "COINGECKO_API_KEY"):
    os.environ[name] = ""
os.environ["EXCHANGERATE_API_KEY"] = "test-exchangerate-key"

from fastapi.testclient import TestClient  # noqa: E402

from service.api.app import create_app  # noqa: E402

QUERIES = Path(__file__).resolve().parents[1] / "tests_data" / "queries.jsonl"


class FakeResponse:
    def __init__(self, data, status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


@pytest.fixture()
def client():
    TMP.mkdir(exist_ok=True)
    db = TMP / "test.db"
    if db.exists():
        db.unlink()
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture()
def http_stub(monkeypatch):
    """Подмена HTTP-вызовов к внешним источникам."""
    calls = []

    def install(data, status_code: int = 200):
        def fake_get(url, params=None, headers=None, timeout=None):
            calls.append({"url": url, "params": dict(params or {}), "headers": dict(headers or {})})
            return FakeResponse(data, status_code)

        monkeypatch.setattr("service.providers.base.httpx.get", fake_get)
        return calls

    return install


@pytest.fixture()
def llm_stub(monkeypatch):
    def install(response):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0000000000")

        def complete_json(self, system, user, max_tokens=700):
            return response(user) if callable(response) else response

        monkeypatch.setattr("service.llm.LLMClient.complete_json", complete_json)

    return install


def load_queries() -> list[dict]:
    return [json.loads(line) for line in QUERIES.read_text(encoding="utf-8").splitlines() if line.strip()]
