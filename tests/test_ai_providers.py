import json

import pytest
import requests

from voiceflow.ai import providers as providers_module
from voiceflow.ai.providers import GroqChatProvider, OpenAITranscriptionProvider, ProviderError


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text or json.dumps(self._json_data)

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._json_data


def test_groq_chat_success(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        assert "chat/completions" in url
        return FakeResponse(200, {"choices": [{"message": {"content": "Hello, formatted!"}}]})

    monkeypatch.setattr(providers_module.requests, "post", fake_post)
    provider = GroqChatProvider(api_key="fake-key")
    result = provider.chat("system prompt", "user text")
    assert result == "Hello, formatted!"


def test_groq_chat_retries_on_429_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            return FakeResponse(429, text="rate limited")
        return FakeResponse(200, {"choices": [{"message": {"content": "done"}}]})

    monkeypatch.setattr(providers_module.requests, "post", fake_post)
    provider = GroqChatProvider(api_key="fake-key", max_retries=3)
    # Avoid real sleeping during the test's retry backoff.
    monkeypatch.setattr(providers_module, "retry_with_backoff", providers_module.retry_with_backoff)
    import voiceflow.utils.retry as retry_module

    monkeypatch.setattr(retry_module.time, "sleep", lambda s: None)

    result = provider.chat("system", "user")
    assert result == "done"
    assert calls["n"] == 3


def test_groq_chat_hard_failure_raises_provider_error(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        return FakeResponse(401, text="invalid api key")

    monkeypatch.setattr(providers_module.requests, "post", fake_post)
    provider = GroqChatProvider(api_key="bad-key")
    with pytest.raises(ProviderError):
        provider.chat("system", "user")


def test_transcription_timeout_wrapped_as_provider_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(providers_module.requests, "post", fake_post)
    import voiceflow.utils.retry as retry_module

    monkeypatch.setattr(retry_module.time, "sleep", lambda s: None)

    provider = OpenAITranscriptionProvider(api_key="fake-key", max_retries=1)
    with pytest.raises(ProviderError):
        provider.transcribe(b"fake wav bytes")


def test_transcription_success_strips_whitespace(monkeypatch):
    def fake_post(url, headers=None, files=None, data=None, timeout=None, **kwargs):
        return FakeResponse(200, {"text": "  hello world  \n"})

    monkeypatch.setattr(providers_module.requests, "post", fake_post)
    provider = OpenAITranscriptionProvider(api_key="fake-key")
    result = provider.transcribe(b"fake wav bytes")
    assert result == "hello world"
