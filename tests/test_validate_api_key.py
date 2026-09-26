import requests

from voiceflow.ai import providers as providers_module
from voiceflow.ai.providers import validate_api_key


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_empty_key_fails_fast_without_network_call(monkeypatch):
    called = []
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: called.append(1))
    ok, message = validate_api_key("groq", "")
    assert ok is False
    assert called == []


def test_groq_valid_key(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: FakeResponse(200))
    ok, message = validate_api_key("groq", "gsk_fake_key")
    assert ok is True
    assert "verified" in message.lower()


def test_groq_invalid_key(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: FakeResponse(401))
    ok, message = validate_api_key("groq", "bad-key")
    assert ok is False
    assert "rejected" in message.lower()


def test_openai_valid_key(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: FakeResponse(200))
    ok, message = validate_api_key("openai", "sk-fake")
    assert ok is True


def test_anthropic_valid_key(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "post", lambda *a, **k: FakeResponse(200))
    ok, message = validate_api_key("anthropic", "sk-ant-fake")
    assert ok is True


def test_rate_limited_key_still_counts_as_valid(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: FakeResponse(429))
    ok, message = validate_api_key("groq", "gsk_fake_key")
    assert ok is True
    assert "rate-limited" in message.lower()


def test_network_timeout_fails_gracefully(monkeypatch):
    def raise_timeout(*a, **k):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(providers_module.requests, "get", raise_timeout)
    ok, message = validate_api_key("groq", "gsk_fake_key")
    assert ok is False
    assert "timed out" in message.lower()


def test_unknown_provider(monkeypatch):
    ok, message = validate_api_key("bogus", "some-key")
    assert ok is False
    assert "unknown provider" in message.lower()


def test_unexpected_status_code(monkeypatch):
    monkeypatch.setattr(providers_module.requests, "get", lambda *a, **k: FakeResponse(500))
    ok, message = validate_api_key("openai", "sk-fake")
    assert ok is False
    assert "500" in message
