import pytest

from voiceflow.ai import transcription as transcription_module
from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.ai.providers import ProviderError
from voiceflow.ai.transcription import TranscriptionService
from voiceflow.config import ConfigManager


class FakeProvider:
    name = "fake"

    def __init__(self, api_key=None, model=None, timeout=None, max_retries=None, model_size=None):
        pass


class AlwaysSucceedsProvider(FakeProvider):
    name = "groq"

    def transcribe(self, wav_bytes, language=None):
        return "transcribed text"


class AlwaysFailsProvider(FakeProvider):
    name = "groq"

    def transcribe(self, wav_bytes, language=None):
        raise ProviderError("groq", "simulated failure")


class SecondSucceedsProvider(FakeProvider):
    name = "openai"

    def transcribe(self, wav_bytes, language=None):
        return "fallback transcript"


def make_config(tmp_path, transcription_order, groq_key="key", openai_key=""):
    cm = ConfigManager(path=tmp_path / "config.json")
    cm.update(
        {
            "providers.transcription_order": transcription_order,
            "providers.groq_api_key": groq_key,
            "providers.openai_api_key": openai_key,
        }
    )
    return cm


def test_no_provider_configured_raises(tmp_path):
    cm = make_config(tmp_path, ["groq", "openai"], groq_key="", openai_key="")
    service = TranscriptionService(cm)
    with pytest.raises(NoProviderConfiguredError):
        service.transcribe(b"wav")


def test_first_provider_success(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription_module, "GroqTranscriptionProvider", AlwaysSucceedsProvider)
    cm = make_config(tmp_path, ["groq"])
    service = TranscriptionService(cm)
    result = service.transcribe(b"wav")
    assert result == "transcribed text"


def test_falls_back_to_second_provider_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription_module, "GroqTranscriptionProvider", AlwaysFailsProvider)
    monkeypatch.setattr(transcription_module, "OpenAITranscriptionProvider", SecondSucceedsProvider)
    cm = make_config(tmp_path, ["groq", "openai"], groq_key="k1", openai_key="k2")
    service = TranscriptionService(cm)
    result = service.transcribe(b"wav")
    assert result == "fallback transcript"


def test_all_providers_failing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription_module, "GroqTranscriptionProvider", AlwaysFailsProvider)
    cm = make_config(tmp_path, ["groq"])
    service = TranscriptionService(cm)
    with pytest.raises(AllProvidersFailedError):
        service.transcribe(b"wav")


def test_provider_without_api_key_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(transcription_module, "GroqTranscriptionProvider", AlwaysFailsProvider)
    monkeypatch.setattr(transcription_module, "OpenAITranscriptionProvider", SecondSucceedsProvider)
    # groq has no key configured -> skipped entirely, openai should be used directly
    cm = make_config(tmp_path, ["groq", "openai"], groq_key="", openai_key="k2")
    service = TranscriptionService(cm)
    result = service.transcribe(b"wav")
    assert result == "fallback transcript"
