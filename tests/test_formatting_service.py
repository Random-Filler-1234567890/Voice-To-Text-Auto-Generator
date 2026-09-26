import pytest

from voiceflow.ai import formatter as formatter_module
from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.ai.formatter import FormattingService
from voiceflow.ai.providers import ProviderError
from voiceflow.config import ConfigManager
from voiceflow.context.app_profiles import get_profile


class FakeProvider:
    name = "fake"

    def __init__(self, api_key=None, model=None, timeout=None, max_retries=None):
        pass


class EchoProvider(FakeProvider):
    name = "groq"

    def chat(self, system_prompt, user_message):
        return f"RESPONSE:{user_message}"


class AlwaysFailsProvider(FakeProvider):
    name = "groq"

    def chat(self, system_prompt, user_message):
        raise ProviderError("groq", "simulated failure")


def make_config(tmp_path, formatting_order=("groq",), groq_key="key"):
    cm = ConfigManager(path=tmp_path / "config.json")
    cm.update(
        {
            "providers.formatting_order": list(formatting_order),
            "providers.groq_api_key": groq_key,
        }
    )
    return cm


def test_no_provider_configured(tmp_path):
    cm = make_config(tmp_path, groq_key="")
    service = FormattingService(cm)
    with pytest.raises(NoProviderConfiguredError):
        service.custom_completion("system", "user")


def test_custom_completion_routes_through_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", EchoProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    result = service.custom_completion("sys prompt", "hello")
    assert result == "RESPONSE:hello"


def test_format_transcript_uses_app_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", EchoProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    profile = get_profile("com.apple.Terminal", "Terminal", "")
    result = service.format_transcript("list files", profile, [])
    assert result == "RESPONSE:list files"


def test_rewrite_text(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", EchoProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    result = service.rewrite_text("make it formal", "hey whats up")
    assert result == "RESPONSE:hey whats up"


def test_clean_meeting_segment(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", EchoProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    result = service.clean_meeting_segment("um so like we discussed")
    assert result == "RESPONSE:um so like we discussed"


def test_summarize_meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", EchoProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    result = service.summarize_meeting("full transcript text")
    assert result == "RESPONSE:full transcript text"


def test_extract_facts_parses_json_response(tmp_path, monkeypatch):
    class FactsProvider(FakeProvider):
        name = "groq"

        def chat(self, system_prompt, user_message):
            return '{"facts": [{"category": "person", "text": "Sarah is my boss"}]}'

    monkeypatch.setattr(formatter_module, "GroqChatProvider", FactsProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    facts = service.extract_facts("my boss is Sarah")
    assert facts == [{"category": "person", "text": "Sarah is my boss"}]


def test_all_providers_failed_propagates(tmp_path, monkeypatch):
    monkeypatch.setattr(formatter_module, "GroqChatProvider", AlwaysFailsProvider)
    cm = make_config(tmp_path)
    service = FormattingService(cm)
    with pytest.raises(AllProvidersFailedError):
        service.custom_completion("sys", "user")
