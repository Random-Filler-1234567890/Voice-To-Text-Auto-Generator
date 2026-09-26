"""HTTP clients for every transcription/formatting backend VoiceFlow supports.

Every provider follows the same contract: raise :class:`ProviderError` on
any failure (after its own internal retry budget is exhausted), so the
orchestrating fallback chain in ``transcription.py`` / ``formatter.py`` can
uniformly catch-and-advance to the next configured provider without each
provider needing bespoke error handling upstream.
"""

from __future__ import annotations

import abc
import json
import logging

import requests

from voiceflow.utils.retry import RetryableError, retry_with_backoff

logger = logging.getLogger("voiceflow.ai.providers")

GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENAI_TRANSCRIPTION_URL = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class ProviderError(Exception):
    """A provider failed (after its own retries) - the caller should try the next one."""

    def __init__(self, provider_name: str, message: str):
        super().__init__(f"[{provider_name}] {message}")
        self.provider_name = provider_name


def _raise_for_http(provider_name: str, response: requests.Response) -> None:
    if response.status_code in _RETRYABLE_STATUS_CODES:
        raise RetryableError(
            f"{provider_name} returned retryable HTTP {response.status_code}: {response.text[:200]}"
        )
    if not response.ok:
        raise ProviderError(
            provider_name, f"HTTP {response.status_code}: {response.text[:300]}"
        )


# ---------------------------------------------------------------------- #
# Transcription providers
# ---------------------------------------------------------------------- #
class TranscriptionProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str: ...


class _WhisperHTTPTranscriptionProvider(TranscriptionProvider):
    """Shared implementation for the OpenAI-compatible /audio/transcriptions endpoint."""

    def __init__(
        self,
        name: str,
        url: str,
        api_key: str,
        model: str,
        timeout: float = 20.0,
        max_retries: int = 2,
    ):
        self.name = name
        self._url = url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str:
        def _do_request() -> str:
            try:
                files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
                data = {"model": self._model, "response_format": "json"}
                if language:
                    data["language"] = language
                response = requests.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    files=files,
                    data=data,
                    timeout=self._timeout,
                )
            except requests.Timeout as exc:
                raise RetryableError(f"{self.name} request timed out: {exc}") from exc
            except requests.ConnectionError as exc:
                raise RetryableError(f"{self.name} connection error: {exc}") from exc

            _raise_for_http(self.name, response)
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise ProviderError(self.name, f"Invalid JSON response: {exc}") from exc
            text = payload.get("text", "")
            return text.strip()

        try:
            return retry_with_backoff(_do_request, max_retries=self._max_retries)
        except RetryableError as exc:
            raise ProviderError(self.name, str(exc)) from exc


class GroqTranscriptionProvider(_WhisperHTTPTranscriptionProvider):
    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo", **kwargs):
        super().__init__("groq", GROQ_TRANSCRIPTION_URL, api_key, model, **kwargs)


class OpenAITranscriptionProvider(_WhisperHTTPTranscriptionProvider):
    def __init__(self, api_key: str, model: str = "whisper-1", **kwargs):
        super().__init__("openai", OPENAI_TRANSCRIPTION_URL, api_key, model, **kwargs)


class LocalWhisperTranscriptionProvider(TranscriptionProvider):
    """Fully offline fallback using ``faster-whisper``. No API key required.

    The model is loaded lazily (and cached) on first use since importing
    faster-whisper/ctranslate2 and loading model weights takes real time -
    we don't want to pay that cost unless the cloud providers actually fail
    or the user has explicitly chosen offline-only operation.
    """

    name = "local"

    def __init__(self, model_size: str = "base.en"):
        self._model_size = model_size
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ProviderError(
                "local",
                "faster-whisper is not installed. Install it with "
                "`pip install faster-whisper` to enable the offline fallback.",
            ) from exc
        logger.info("Loading local Whisper model %r (first use only)...", self._model_size)
        self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, wav_bytes: bytes, language: str | None = None) -> str:
        import io

        model = self._ensure_model()
        try:
            segments, _info = model.transcribe(io.BytesIO(wav_bytes), language=language)
            return " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise ProviderError("local", f"Local transcription failed: {exc}") from exc


# ---------------------------------------------------------------------- #
# Formatting (chat) providers
# ---------------------------------------------------------------------- #
class FormattingProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def chat(self, system_prompt: str, user_message: str) -> str: ...


class GroqChatProvider(FormattingProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        timeout: float = 15.0,
        max_retries: int = 2,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

    def chat(self, system_prompt: str, user_message: str) -> str:
        def _do_request() -> str:
            try:
                response = requests.post(
                    GROQ_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.2,
                    },
                    timeout=self._timeout,
                )
            except requests.Timeout as exc:
                raise RetryableError(f"groq request timed out: {exc}") from exc
            except requests.ConnectionError as exc:
                raise RetryableError(f"groq connection error: {exc}") from exc

            _raise_for_http("groq", response)
            payload = response.json()
            return payload["choices"][0]["message"]["content"].strip()

        try:
            return retry_with_backoff(_do_request, max_retries=self._max_retries)
        except RetryableError as exc:
            raise ProviderError("groq", str(exc)) from exc


class OpenAIChatProvider(FormattingProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        timeout: float = 15.0,
        max_retries: int = 2,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

    def chat(self, system_prompt: str, user_message: str) -> str:
        def _do_request() -> str:
            try:
                response = requests.post(
                    OPENAI_CHAT_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.2,
                    },
                    timeout=self._timeout,
                )
            except requests.Timeout as exc:
                raise RetryableError(f"openai request timed out: {exc}") from exc
            except requests.ConnectionError as exc:
                raise RetryableError(f"openai connection error: {exc}") from exc

            _raise_for_http("openai", response)
            payload = response.json()
            return payload["choices"][0]["message"]["content"].strip()

        try:
            return retry_with_backoff(_do_request, max_retries=self._max_retries)
        except RetryableError as exc:
            raise ProviderError("openai", str(exc)) from exc


class AnthropicChatProvider(FormattingProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        timeout: float = 15.0,
        max_retries: int = 2,
    ):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

    def chat(self, system_prompt: str, user_message: str) -> str:
        def _do_request() -> str:
            try:
                response = requests.post(
                    ANTHROPIC_MESSAGES_URL,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "max_tokens": 1024,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": user_message}],
                    },
                    timeout=self._timeout,
                )
            except requests.Timeout as exc:
                raise RetryableError(f"anthropic request timed out: {exc}") from exc
            except requests.ConnectionError as exc:
                raise RetryableError(f"anthropic connection error: {exc}") from exc

            _raise_for_http("anthropic", response)
            payload = response.json()
            return "".join(block.get("text", "") for block in payload.get("content", [])).strip()

        try:
            return retry_with_backoff(_do_request, max_retries=self._max_retries)
        except RetryableError as exc:
            raise ProviderError("anthropic", str(exc)) from exc


def validate_api_key(provider: str, api_key: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Make one cheap, real API call to confirm a key actually works.

    Used by the Quick Setup flow so the user gets immediate "yes this works"
    or "no, here's why" feedback instead of silently saving a typo'd or
    expired key and only discovering it's broken the next time they dictate.
    """
    if not api_key or not api_key.strip():
        return False, "No key entered."

    try:
        if provider == "groq":
            response = requests.get(
                GROQ_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
            )
        elif provider == "openai":
            response = requests.get(
                OPENAI_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout
            )
        elif provider == "anthropic":
            response = requests.post(
                ANTHROPIC_MESSAGES_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=timeout,
            )
        else:
            return False, f"Unknown provider: {provider}"
    except requests.Timeout:
        return False, "Validation timed out - check your internet connection and try again."
    except requests.ConnectionError:
        return False, "Couldn't reach the API - check your internet connection and try again."
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"

    if response.status_code == 200:
        return True, "Key verified!"
    if response.status_code == 401:
        return False, "That key was rejected (invalid or revoked)."
    if response.status_code == 429:
        # The key IS valid - it's just rate-limited/out of quota, which is a
        # perfectly usable state (transient), so treat this as a pass.
        return True, "Key verified (currently rate-limited, but valid)."
    return False, f"Unexpected response from {provider} (HTTP {response.status_code})."
