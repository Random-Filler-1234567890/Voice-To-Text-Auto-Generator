"""LLM-based transcript formatting and 'Learn:' fact extraction, with fallback chain."""

from __future__ import annotations

import logging

from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.ai.prompts import (
    FACT_EXTRACTION_SYSTEM_PROMPT,
    build_fact_extraction_user_message,
    build_formatting_system_prompt,
    parse_json_object,
)
from voiceflow.ai.providers import (
    AnthropicChatProvider,
    FormattingProvider,
    GroqChatProvider,
    OpenAIChatProvider,
    ProviderError,
)
from voiceflow.config import ConfigManager
from voiceflow.context.app_profiles import AppProfile

logger = logging.getLogger("voiceflow.ai.formatter")


class FormattingService:
    def __init__(self, config: ConfigManager):
        self._config = config

    def _build_provider(self, name: str) -> FormattingProvider | None:
        timeout = self._config.get("providers.request_timeout_seconds", 20)
        max_retries = self._config.get("providers.max_retries", 3)

        if name == "groq":
            key = self._config.get("providers.groq_api_key", "")
            if not key:
                return None
            model = self._config.get("providers.groq_formatting_model", "llama-3.3-70b-versatile")
            return GroqChatProvider(key, model=model, timeout=timeout, max_retries=max_retries)

        if name == "openai":
            key = self._config.get("providers.openai_api_key", "")
            if not key:
                return None
            model = self._config.get("providers.openai_formatting_model", "gpt-4o-mini")
            return OpenAIChatProvider(key, model=model, timeout=timeout, max_retries=max_retries)

        if name == "anthropic":
            key = self._config.get("providers.anthropic_api_key", "")
            if not key:
                return None
            model = self._config.get("providers.anthropic_formatting_model", "claude-haiku-4-5-20251001")
            return AnthropicChatProvider(key, model=model, timeout=timeout, max_retries=max_retries)

        logger.warning("Unknown formatting provider in config: %r", name)
        return None

    def _providers(self) -> list[FormattingProvider]:
        order = self._config.get("providers.formatting_order", [])
        return [p for p in (self._build_provider(n) for n in order) if p is not None]

    def _run_chain(self, system_prompt: str, user_message: str) -> str:
        providers = self._providers()
        if not providers:
            raise NoProviderConfiguredError(
                "No formatting provider is configured. Add a Groq, OpenAI, or "
                "Anthropic API key in Settings."
            )
        last_error: Exception | None = None
        for provider in providers:
            try:
                result = provider.chat(system_prompt, user_message)
                if result:
                    logger.info("Formatted via %s (%d chars)", provider.name, len(result))
                    return result
                logger.warning("%s returned an empty response, trying next provider", provider.name)
            except ProviderError as exc:
                logger.error("Formatting provider %r failed: %s", provider.name, exc)
                last_error = exc
                continue
        raise AllProvidersFailedError(
            f"All configured formatting providers failed. Last error: {last_error}"
        )

    def format_transcript(
        self,
        raw_transcript: str,
        app_profile: AppProfile,
        memory_snippets: list[str],
    ) -> str:
        system_prompt = build_formatting_system_prompt(
            app_profile=app_profile,
            memory_snippets=memory_snippets,
            remove_filler_words=self._config.get("formatting.remove_filler_words", True),
            auto_punctuate=self._config.get("formatting.auto_punctuate", True),
            preserve_tone=self._config.get("formatting.preserve_tone", True),
        )
        return self._run_chain(system_prompt, raw_transcript)

    def extract_facts(self, raw_learn_statement: str) -> list[dict]:
        """Call the LLM to turn a 'Learn: ...' statement into structured facts.

        Returns ``[]`` (never raises for parse issues) if the model's
        response can't be parsed as JSON, so a malformed extraction just
        results in nothing being learned rather than crashing the pipeline.
        """
        user_message = build_fact_extraction_user_message(raw_learn_statement)
        try:
            raw_response = self._run_chain(FACT_EXTRACTION_SYSTEM_PROMPT, user_message)
        except (NoProviderConfiguredError, AllProvidersFailedError):
            raise

        try:
            parsed = parse_json_object(raw_response)
            facts = parsed.get("facts", [])
            if not isinstance(facts, list):
                logger.warning("Fact extraction response had non-list 'facts': %r", parsed)
                return []
            return facts
        except Exception:
            logger.exception("Failed to parse fact extraction response: %r", raw_response)
            return []
