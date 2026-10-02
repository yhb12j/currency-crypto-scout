import json

from tests.conftest import load_queries

CRYPTO = "Собери топ-10 криптовалют по капитализации в долларах и сохрани поля: rank, name, symbol, price, change_24h"
FX = "Собери текущие котировки доллара, евро и юаня к рублю"
MARKET_ROW = {
    "id": "bitcoin", "symbol": "btc", "name": "Bitcoin", "current_price": 84727, "market_cap": 1702316865338,
    "market_cap_rank": 1, "total_volume": 33472815109, "price_change_percentage_24h_in_currency": 1.19503,
    "price_change_percentage_7d_in_currency": 0.4659, "last_updated": "2026-10-01T23:23:30.000Z", "image": "x",
}
FX_OK = {"success": True, "timestamp": 1790897165, "source": "USD",
         "quotes": {"USDRUB": 83.0, "USDEUR": 0.83, "USDCNY": 6.64}}


def dataset(client, source="CoinGecko", name="Набор"):
    response = client.post("/datasets", json={"name": name, "source": source})
    assert response.status_code == 200
    return response.json()["dataset_id"]


def audit(client, **params):
    return client.get("/audit/runs", params=params).json()


def test_index_and_health(client):
    page = client.get("/")
    assert page.status_code == 200
    for title in ("Наборы данных", "Сбор", "Витрина", "Аудит", "Нужна ручная проверка запроса"):
        assert title in page.text
    assert client.get("/health").json()["status"] == "ok"


def test_create_dataset_contract_and_validation(client):
    assert client.post("/datasets", json={"name": "", "source": "CoinGecko"}).status_code == 400
    assert client.post("/datasets", json={"name": "A", "source": " "}).status_code == 400
    assert client.post("/datasets", json={"name": "A", "source": "Binance"}).status_code == 422
    body = client.post("/datasets", json={"name": "Крипто", "source": "coingecko"}).json()
    assert body["status"] == "ok" and len(body["dataset_id"]) == 36
    listed = client.get("/datasets").json()
    assert listed[0]["dataset_id"] == body["dataset_id"] and listed[0]["source"] == "CoinGecko"
    assert [a["status"] for a in audit(client)] == ["ok", "error", "error", "error"]


def test_reference_queries_through_api(client):
    ids = {"CoinGecko": dataset(client), "exchangerate.host": dataset(client, "exchangerate.host")}
    for row in load_queries():
        body = client.post("/ai/plan_and_collect", json={"query": row["query"], "dataset_id": ids[row["source"]]}).json()
        assert body["needs_review"] is row["expected_needs_review"], row["query"]
        assert set(body) >= {"plan_steps", "api_url", "fields_to_keep", "confidence", "needs_review"}
        assert body["api_url"] == "" if body["needs_review"] else body["api_url"].startswith("https://api.")
    held = client.get("/agent_runs", params={"needs_review": True}).json()
    assert len(held) == 3 and all(r["error"] for r in held)
    assert client.get("/audit/summary").json()["needs_review"] == 3


def test_model_cannot_relax_policy(client, llm_stub):
    llm_stub({"plan_steps": ["Собрать всё"], "api_url": "https://evil.example", "fields_to_keep": ["password"],
              "confidence": "high", "needs_review": False, "reason": "ok"})
    held = client.post("/ai/plan_and_collect", json={"query": "Собери самое важное"}).json()
    assert held["needs_review"] is True
    allowed = client.post("/ai/plan_and_collect", json={"query": CRYPTO}).json()
    assert allowed["needs_review"] is False
    assert allowed["api_url"].startswith("https://api.coingecko.com/") and "password" not in allowed["fields_to_keep"]
    assert allowed["plan_steps"][0] == "Собрать всё"


def test_model_low_confidence_holds_collection(client, llm_stub):
    llm_stub({"plan_steps": ["Стоп"], "api_url": "", "fields_to_keep": [], "confidence": "low",
              "needs_review": True, "reason": "неоднозначный список монет"})
    body = client.post("/ai/plan_and_collect", json={"query": CRYPTO}).json()
    assert body["needs_review"] is True and "неоднозначный список монет" in body["reason"]
    assert body["decided_by"] == "model"


def test_contract_violation_holds_collection(client, llm_stub):
    llm_stub({"plan_steps": "текст", "confidence": "maybe"})
    body = client.post("/ai/plan_and_collect", json={"query": CRYPTO}).json()
    assert body["needs_review"] is True and "контракту JSON" in body["reason"]


def test_held_query_never_calls_provider(client, monkeypatch):
    def forbidden(*_a, **_k):
        raise AssertionError("внешний вызов при ручной проверке")

    monkeypatch.setattr("service.providers.base.httpx.get", forbidden)
    dataset_id = dataset(client)
    for query in ("Собери самое важное", "Собери данные по рынку и сделай вывод", ""):
        response = client.post(f"/datasets/{dataset_id}/collect", json={"query": query})
        assert response.status_code == 422
        assert response.json()["status"] == "needs_review" and response.json()["records_saved"] == 0
    assert len(audit(client, status="needs_review")) == 3


def test_collect_reuses_plan_from_planning(client, llm_stub, http_stub):
    http_stub([MARKET_ROW])
    dataset_id = dataset(client)
    llm_stub({"plan_steps": ["Шаг"], "api_url": "", "fields_to_keep": [], "confidence": "high",
              "needs_review": False, "reason": ""})
    client.post("/ai/plan_and_collect", json={"query": CRYPTO, "dataset_id": dataset_id})
    llm_stub({"plan_steps": ["Стоп"], "api_url": "", "fields_to_keep": [], "confidence": "low",
              "needs_review": True, "reason": "другое решение"})
    assert client.post(f"/datasets/{dataset_id}/collect", json={"query": CRYPTO}).status_code == 200


def test_crypto_collect_keeps_only_planned_fields(client, http_stub):
    calls = http_stub([MARKET_ROW])
    dataset_id = dataset(client)
    response = client.post(f"/datasets/{dataset_id}/collect", json={"query": CRYPTO})
    assert response.json() == {"status": "ok", "records_saved": 1}
    assert calls[0]["params"]["vs_currency"] == "usd" and calls[0]["params"]["per_page"] == "10"
    record = client.get(f"/datasets/{dataset_id}/records", params={"limit": 50}).json()[0]
    assert record["created_at"] and record["dataset_id"] == dataset_id and record["source"] == "CoinGecko"
    assert record["record_json"] == {"rank": 1, "name": "Bitcoin", "symbol": "BTC", "price": 84727,
                                     "currency": "USD", "change_24h": 1.2}


def test_fx_collect_cross_rates_and_secret_redaction(client, http_stub):
    calls = http_stub(FX_OK)
    dataset_id = dataset(client, "exchangerate.host")
    assert client.post(f"/datasets/{dataset_id}/collect", json={"query": FX}).json()["records_saved"] == 3
    rates = {r["record_json"]["currency"]: r["record_json"]["rate"]
             for r in client.get(f"/datasets/{dataset_id}/records").json()}
    assert rates == {"USD": 83.0, "EUR": 100.0, "CNY": 12.5}
    assert calls[0]["params"]["access_key"] == "test-exchangerate-key"
    assert "test-exchangerate-key" not in json.dumps(audit(client), ensure_ascii=False)


def test_unknown_dataset_is_404_and_audited(client):
    assert client.post("/datasets/missing/collect", json={"query": CRYPTO}).status_code == 404
    assert client.get("/datasets/missing/records").status_code == 404
    assert {a["action"] for a in audit(client, status="error")} == {"collect", "list_records"}


def test_provider_rate_limit_is_502_and_audited(client, http_stub):
    http_stub({}, 429)
    dataset_id = dataset(client)
    assert client.post(f"/datasets/{dataset_id}/collect", json={"query": CRYPTO}).status_code == 502
    entry = audit(client, action="collect")[0]
    assert entry["status"] == "error" and "лимит" in entry["error"]


def test_fx_provider_error_codes(client, http_stub):
    http_stub({"success": False, "error": {"code": 104, "type": "usage_limit_reached"}})
    dataset_id = dataset(client, "exchangerate.host")
    response = client.post(f"/datasets/{dataset_id}/collect", json={"query": FX})
    assert response.status_code == 502 and "лимит" in response.json()["detail"]


def test_missing_fx_key_is_500(client, monkeypatch):
    monkeypatch.setenv("EXCHANGERATE_API_KEY", "")
    dataset_id = dataset(client, "exchangerate.host")
    response = client.post(f"/datasets/{dataset_id}/collect", json={"query": FX})
    assert response.status_code == 500 and "EXCHANGERATE_API_KEY" in response.json()["detail"]


def test_records_limit_validation(client):
    dataset_id = dataset(client)
    assert client.get(f"/datasets/{dataset_id}/records", params={"limit": 0}).status_code == 422
    assert client.get(f"/datasets/{dataset_id}/records", params={"limit": 501}).status_code == 422


def test_export_json_and_csv(client, http_stub):
    http_stub([MARKET_ROW])
    dataset_id = dataset(client)
    client.post(f"/datasets/{dataset_id}/collect", json={"query": CRYPTO})
    as_json = client.get(f"/datasets/{dataset_id}/export", params={"format": "json"})
    assert as_json.status_code == 200 and as_json.json()[0]["record_json"]["name"] == "Bitcoin"
    as_csv = client.get(f"/datasets/{dataset_id}/export", params={"format": "csv"}).text
    assert "id;created_at;dataset_id;source;rank;name;symbol;price;currency;change_24h" in as_csv
    assert client.get(f"/datasets/{dataset_id}/export", params={"format": "xml"}).status_code == 422


def test_ask_is_withheld_without_evidence(client, llm_stub, http_stub):
    dataset_id = dataset(client)
    assert client.post(f"/datasets/{dataset_id}/ask", json={"question": "Цена bitcoin?"}).json()["needs_review"]
    assert client.post(f"/datasets/{dataset_id}/ask", json={"question": "Прогноз на завтра"}).json()["needs_review"]
    http_stub([MARKET_ROW])
    client.post(f"/datasets/{dataset_id}/collect", json={"query": CRYPTO})
    record_id = client.get(f"/datasets/{dataset_id}/records").json()[0]["id"]

    llm_stub({"answer": "1 USD", "used_record_ids": [987654], "confidence": "high", "needs_review": False, "reason": ""})
    assert client.post(f"/datasets/{dataset_id}/ask", json={"question": "Цена bitcoin?"}).json()["needs_review"]

    llm_stub({"answer": "84 727 USD", "used_record_ids": [record_id], "confidence": "high",
              "needs_review": False, "reason": "запись rank 1"})
    body = client.post(f"/datasets/{dataset_id}/ask", json={"question": "Цена bitcoin?"}).json()
    assert body["needs_review"] is False and body["used_record_ids"] == [record_id]
