"""Speech-to-text with an ordered, automatic fallback chain.

The order and which providers are "in" is entirely config-driven (see
``providers.transcription_order`` in ``config.py``) - a provider is
skipped automatically if it has no API key configured. If every
cloud provider fails (or none is configured), and a ``local`` entry is
present in the order, it falls through to the fully-offline
``faster-whisper`` provider so dictation still works without internet.
"""

from __future__ import annotations

import logging

from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.ai.providers import (
    GroqTranscriptionProvider,
    LocalWhisperTranscriptionProvider,
    OpenAITranscriptionProvider,
    ProviderError,
    TranscriptionProvider,
)
from voiceflow.config import ConfigManager

logger = logging.getLogger("voiceflow.ai.transcription")


class TranscriptionService:
    def __init__(self, config: ConfigManager):
        self._config = config

    def _build_provider(self, name: str) -> TranscriptionProvider | None:
        timeout = self._config.get("providers.request_timeout_seconds", 20)
        max_retries = self._config.get("providers.max_retries", 3)

        if name == "groq":
            key = self._config.get("providers.groq_api_key", "")
            if not key:
                return None
            model = self._config.get("providers.groq_transcription_model", "whisper-large-v3-turbo")
            return GroqTranscriptionProvider(key, model=model, timeout=timeout, max_retries=max_retries)

        if name == "openai":
            key = self._config.get("providers.openai_api_key", "")
            if not key:
                return None
            model = self._config.get("providers.openai_transcription_model", "whisper-1")
            return OpenAITranscriptionProvider(key, model=model, timeout=timeout, max_retries=max_retries)

        if name == "local":
            model_size = self._config.get("providers.local_whisper_model_size", "base.en")
            return LocalWhisperTranscriptionProvider(model_size=model_size)

        logger.warning("Unknown transcription provider in config: %r", name)
        return None

    def transcribe(self, wav_bytes: bytes) -> str:
        order = self._config.get("providers.transcription_order", [])
        providers = [p for p in (self._build_provider(n) for n in order) if p is not None]

        if not providers:
            raise NoProviderConfiguredError(
                "No transcription provider is configured. Add a Groq or OpenAI API "
                "key in Settings, or enable the local faster-whisper fallback."
            )

        last_error: Exception | None = None
        for provider in providers:
            try:
                text = provider.transcribe(wav_bytes)
                if text:
                    logger.info("Transcribed via %s (%d chars)", provider.name, len(text))
                    return text
                logger.warning("%s returned an empty transcript, trying next provider", provider.name)
            except ProviderError as exc:
                logger.error("Transcription provider %r failed: %s", provider.name, exc)
                last_error = exc
                continue

        raise AllProvidersFailedError(
            f"All configured transcription providers failed. Last error: {last_error}"
        )
