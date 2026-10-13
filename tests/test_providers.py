import json
import logging

import httpx
import pytest

from survey_sim.errors import ProviderError, AppError
from survey_sim.models import ProviderConfig
from survey_sim.providers import HTTPProvider, parse_json, make_provider, test_connection as connection_check
from survey_sim.security import SecretStore, redact, register_secret, clean_url


@pytest.mark.parametrize("provider,endpoint,response", [
    ("openai", "/v1/chat/completions", {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}),
    ("deepseek", "/chat/completions", {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}),
    ("compatible", "/v1/chat/completions", {"choices": [{"message": {"content": '{"ok":true}'}}], "usage": {"prompt_tokens": 10, "completion_tokens": 3}}),
    ("anthropic", "/v1/messages", {"content": [{"type": "text", "text": '{"ok":true}'}], "usage": {"input_tokens": 10, "output_tokens": 3}}),
    ("gemini", "/v1beta/models/test-model:generateContent", {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"ok":true}'}]}}], "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3}}),
    ("ollama", "/api/chat", {"message": {"content": '{"ok":true}'}, "prompt_eval_count": 10, "eval_count": 3})])
def test_provider_specific_wire_contract(provider, endpoint, response):
    records = []
    def handle(request):
        assert request.url.path == endpoint
        payload = json.loads(request.content)
        if provider == "anthropic":
            assert request.headers["x-api-key"] == "test-secret"
            assert request.headers["anthropic-version"] == "2023-06-01"
            assert "system" in payload and "response_format" not in payload
        elif provider == "gemini":
            assert request.headers["x-goog-api-key"] == "test-secret"
            assert "systemInstruction" in payload and payload["generationConfig"]["responseMimeType"] == "application/json"
        elif provider == "ollama":
            assert payload["stream"] is False and payload["format"] == "json"
        else:
            assert request.headers["Authorization"] == "Bearer test-secret"
            assert ("max_tokens" in payload) if provider == "deepseek" else ("max_completion_tokens" in payload)
        return httpx.Response(200, json=response)
    urls = {"compatible": "https://example.com/v1"}
    c = ProviderConfig(provider=provider, model="test-model", base_url=urls.get(provider, ""), input_price_per_million=1, output_price_per_million=2, rate_source="verified-test")
    p = HTTPProvider(c, "test-secret", records.append, httpx.MockTransport(handle))
    result = connection_check(p)
    assert result.input_tokens == 10 and result.output_tokens == 3
    assert records[0]["cost"] == pytest.approx(.000016)
    assert "test-secret" not in json.dumps(records)


def test_retry_rate_limit_and_cost_unknown(monkeypatch):
    monkeypatch.setattr("survey_sim.providers.time.sleep", lambda _: None)
    count = 0
    usage = []
    def handle(request):
        nonlocal count
        count += 1
        if count == 1: return httpx.Response(429, headers={"Retry-After": "0"}, json={"error": "limit"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    p = HTTPProvider(ProviderConfig(provider="openai", retries=1), "key-test-1234", usage.append, httpx.MockTransport(handle))
    assert p.generate("test", {}, "JSON").data["ok"]
    assert count == 2 and all(x["cost"] is None for x in usage)


@pytest.mark.parametrize("status,message", [(401, "API Key"), (402, "額度"), (400, "參數"), (404, "模型")])
def test_user_friendly_api_errors_hide_server_body(status, message):
    p = HTTPProvider(ProviderConfig(provider="openai"), "private-key", transport=httpx.MockTransport(lambda r: httpx.Response(status, json={"error": "private-key"})))
    with pytest.raises(ProviderError, match=message) as err: p.generate("test", {}, "JSON")
    assert "private-key" not in str(err.value)


def test_json_output_validation_and_mock_without_key(config):
    assert connection_check(make_provider(config)).data["ok"]
    assert parse_json('```json\n{"x":1}\n```') == {"x": 1}
    for data in ["not json", "[1]", '{"x":NaN}', '{"x":1} trailing']:
        with pytest.raises(ProviderError): parse_json(data)
    with pytest.raises(ProviderError): HTTPProvider(ProviderConfig(provider="openai"))


def test_secret_redaction_and_db_does_not_store_key(db, monkeypatch):
    key = "unit-key-do-not-export"
    secret = SecretStore()
    c = ProviderConfig(id="secret-test")
    secret.put(c.id, key)
    assert secret.get(c.id, "mock") == key
    assert key not in redact(f"authorization Bearer {key} api_key={key}")
    db.save("provider", c)
    assert key.encode() not in db.path.read_bytes()
    assert "api_key" not in c.model_dump()


def test_exact_urls_no_embedded_credentials():
    assert clean_url("https://example.com/form/") == "https://example.com/form"
    for url in ["https://user:pass@example.com/form", "file:///tmp/form", "https://example.com/api?key=secret", "http://example.com/api"]:
        with pytest.raises(AppError): clean_url(url, api=True)


@pytest.mark.parametrize("wire", [[1], {"choices": []}, {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 20}}])
def test_malformed_or_truncated_provider_outputs_are_recorded(wire):
    usage = []
    p = HTTPProvider(ProviderConfig(provider="openai"), "test-key", usage.append,
                     httpx.MockTransport(lambda request: httpx.Response(200, json=wire)))
    with pytest.raises(ProviderError):
        p.generate("test", {}, "JSON")
    assert len(usage) == 1 and usage[0]["status"] == "invalid_response"
    if isinstance(wire, dict) and wire.get("usage"):
        assert usage[0]["output_tokens"] == 20
