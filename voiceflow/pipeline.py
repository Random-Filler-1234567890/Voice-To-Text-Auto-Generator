"""The orchestrator that wires every component into the end-to-end dictation flow.

record -> transcribe -> (learn | format) -> inject

This module intentionally takes every dependency through its constructor
(dependency injection) rather than importing concrete rumps/AppKit/pynput
code itself, so the entire pipeline's *decision logic* - what happens on a
too-short recording, how a "Learn:" command is routed differently from
normal dictation, how provider failures are surfaced - can be unit tested
with fake services, independent of any macOS API.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.ai.prompts import strip_prefix
from voiceflow.clipboard.injector import InjectionError, PyperclipBackend
from voiceflow.config import ConfigManager
from voiceflow.context.app_profiles import AppCategory, AppProfile, get_profile
from voiceflow.state import AppState, StateManager

logger = logging.getLogger("voiceflow.pipeline")

MIN_RECORDING_SECONDS = 0.25

# Peak amplitude (0.0-1.0) below which a recording is treated as
# effectively silent - wrong input device selected, microphone muted, OS
# mic permission not actually granted, etc. Chosen conservatively low so it
# only fires for genuine silence, never for someone just speaking quietly;
# skipping the transcription API call in that case is both faster and
# avoids burning a request on audio that's essentially guaranteed to come
# back empty anyway.
MIN_USEFUL_PEAK_AMPLITUDE = 0.01

_DEFAULT_PROFILE = AppProfile(
    AppCategory.DEFAULT,
    "Default",
    "Clean up filler words and grammar while strictly preserving the user's "
    "meaning and tone. Use plain prose with normal sentence punctuation.",
)


@dataclass
class PipelineResult:
    # "injected" | "learned" | "edited" | "ignored_too_short" | "ignored_silent"
    # | "ignored_empty" | "injection_failed"
    kind: str
    text: Optional[str] = None
    learned_count: int = 0


class NotifyLevel:
    INFO = "info"
    ERROR = "error"


class DictationPipeline:
    def __init__(
        self,
        config: ConfigManager,
        state: StateManager,
        audio_recorder,
        transcription_service,
        formatting_service,
        memory_store,
        clipboard_injector,
        context_detector,
        on_notify: Optional[Callable[[str, str, str], None]] = None,
        on_result: Optional[Callable[[PipelineResult], None]] = None,
        history=None,
        stats=None,
        clipboard_reader=None,
    ) -> None:
        self._config = config
        self._state = state
        self._audio = audio_recorder
        self._transcription = transcription_service
        self._formatting = formatting_service
        self._memory = memory_store
        self._injector = clipboard_injector
        self._context = context_detector
        self._on_notify = on_notify or (lambda title, msg, level: None)
        self._on_result = on_result or (lambda result: None)
        self._history = history
        self._stats = stats
        self._clipboard_reader = clipboard_reader or PyperclipBackend()
        self._captured_context = None

    # ------------------------------------------------------------------ #
    # Entry points called by the hotkey listener
    # ------------------------------------------------------------------ #
    def start_recording(self) -> None:
        if self._state.state != AppState.IDLE:
            logger.warning("start_recording ignored - not idle (state=%s)", self._state.state)
            return

        self._state.new_generation()
        if not self._state.transition(AppState.RECORDING):
            return

        try:
            self._captured_context = self._context.get_frontmost_context()
        except Exception:
            logger.exception("Failed to capture frontmost app context")
            self._captured_context = None

        try:
            self._audio.start(on_max_duration_exceeded=self.stop_recording)
        except Exception as exc:
            logger.exception("Failed to start audio recording")
            self._on_notify("VoiceFlow", f"Couldn't access the microphone: {exc}", NotifyLevel.ERROR)
            self._state.force_idle()

    def stop_recording(self) -> None:
        if self._state.state != AppState.RECORDING:
            logger.warning("stop_recording ignored - not recording (state=%s)", self._state.state)
            return

        generation = self._state.generation
        try:
            result = self._audio.stop()
        except Exception:
            logger.exception("Failed to stop audio recording")
            self._on_notify("VoiceFlow", "Recording failed unexpectedly.", NotifyLevel.ERROR)
            self._state.force_idle()
            return

        if not self._state.transition(AppState.TRANSCRIBING):
            return

        thread = threading.Thread(
            target=self._process, args=(result, generation), daemon=True, name="voiceflow-pipeline"
        )
        thread.start()

    def cancel(self) -> None:
        """Abort whatever is in flight and return to idle (best-effort)."""
        if self._state.state == AppState.RECORDING:
            try:
                self._audio.cancel()
            except Exception:
                logger.exception("Error cancelling audio recording")
        self._state.force_idle()

    # ------------------------------------------------------------------ #
    # Background processing (runs off the hotkey-listener thread)
    # ------------------------------------------------------------------ #
    def _process(self, recording_result, generation: int) -> None:
        if not self._state.is_current_generation(generation):
            return

        if recording_result.duration_seconds < MIN_RECORDING_SECONDS:
            logger.info("Recording too short (%.2fs); ignoring", recording_result.duration_seconds)
            self._state.force_idle()
            self._on_result(PipelineResult(kind="ignored_too_short"))
            return

        if recording_result.peak_amplitude < MIN_USEFUL_PEAK_AMPLITUDE:
            logger.info(
                "Recording had negligible audio level (peak=%.4f); skipping transcription",
                recording_result.peak_amplitude,
            )
            self._state.force_idle()
            self._on_notify(
                "VoiceFlow",
                "Didn't detect any audio - check that the right microphone is selected "
                "(menu -> Audio -> Input Device) and that it isn't muted.",
                NotifyLevel.ERROR,
            )
            self._on_result(PipelineResult(kind="ignored_silent"))
            return

        try:
            raw_text = self._transcription.transcribe(recording_result.wav_bytes)
        except NoProviderConfiguredError as exc:
            self._fail(str(exc), configure_hint=True)
            return
        except AllProvidersFailedError as exc:
            self._fail(f"Transcription failed: {exc}")
            return
        except Exception:
            logger.exception("Unexpected transcription error")
            self._fail("Transcription failed unexpectedly. Check the log for details.")
            return

        if not self._state.is_current_generation(generation):
            return

        if not raw_text.strip():
            logger.info("Empty transcript (silence?); ignoring")
            self._state.force_idle()
            if recording_result.clipped:
                self._on_notify(
                    "VoiceFlow",
                    "Didn't catch that - your audio was clipping (too loud). Try lowering "
                    "your microphone input volume in System Settings.",
                    NotifyLevel.ERROR,
                )
            self._on_result(PipelineResult(kind="ignored_empty"))
            return

        learn_prefixes = self._config.get("formatting.learn_prefixes", ["learn:", "remember:"])
        is_learn, learn_remainder = strip_prefix(raw_text, learn_prefixes)
        if is_learn:
            self._handle_learn(learn_remainder or raw_text, generation)
            return

        edit_prefixes = self._config.get("formatting.edit_prefixes", ["edit:", "rewrite:"])
        is_edit, edit_remainder = strip_prefix(raw_text, edit_prefixes)
        if is_edit and edit_remainder:
            self._handle_edit_command(edit_remainder, generation)
            return

        self._handle_dictation(raw_text, generation)

    def _handle_learn(self, statement: str, generation: int) -> None:
        if not self._state.transition(AppState.LEARNING):
            return
        try:
            facts = self._formatting.extract_facts(statement)
            added = self._memory.learn_from_facts(facts)
        except NoProviderConfiguredError as exc:
            self._fail(str(exc), configure_hint=True)
            return
        except AllProvidersFailedError as exc:
            self._fail(f"Couldn't process 'Learn:' command: {exc}")
            return
        except Exception:
            logger.exception("Unexpected error extracting facts")
            self._fail("Couldn't process the 'Learn:' command unexpectedly.")
            return

        if not self._state.is_current_generation(generation):
            return

        self._state.transition(AppState.IDLE)
        if added:
            summary = "; ".join(f"[{e.category}] {e.text}" for e in added[:3])
            self._on_notify("VoiceFlow learned something new", summary, NotifyLevel.INFO)
            if self._stats is not None:
                for _ in added:
                    self._stats.record_fact_learned()
        else:
            self._on_notify(
                "VoiceFlow", "Didn't find a clear fact to learn from that.", NotifyLevel.INFO
            )
        self._on_result(PipelineResult(kind="learned", learned_count=len(added)))

    def _handle_dictation(self, raw_text: str, generation: int) -> None:
        if not self._state.transition(AppState.FORMATTING):
            return

        overrides = self._config.get("app_profiles_overrides", {})
        if self._captured_context is not None:
            profile = get_profile(
                bundle_id=self._captured_context.bundle_id,
                app_name=self._captured_context.app_name,
                window_title=self._captured_context.window_title,
                overrides=overrides,
            )
        else:
            profile = _DEFAULT_PROFILE

        max_snippets = self._config.get("memory.max_snippets_injected", 8)
        snippets = self._memory.relevant_snippets(raw_text, max_results=max_snippets)

        try:
            formatted = self._formatting.format_transcript(raw_text, profile, snippets)
        except NoProviderConfiguredError as exc:
            self._fail(str(exc), configure_hint=True)
            return
        except AllProvidersFailedError:
            logger.warning("Formatting failed; falling back to raw transcript")
            formatted = raw_text
        except Exception:
            logger.exception("Unexpected formatting error; falling back to raw transcript")
            formatted = raw_text

        if not self._state.is_current_generation(generation):
            return

        if not self._state.transition(AppState.INJECTING):
            return

        try:
            self._injector.inject(
                formatted,
                on_restored=lambda: self._on_generation_idle(generation),
            )
        except InjectionError as exc:
            logger.error("Injection failed: %s", exc)
            self._on_notify(
                "VoiceFlow",
                "Transcribed, but couldn't paste it automatically. "
                "It's on your clipboard - press Cmd+V to paste it yourself.",
                NotifyLevel.ERROR,
            )
            try:
                from voiceflow.clipboard.injector import PyperclipBackend

                PyperclipBackend().copy(formatted)
            except Exception:
                logger.exception("Even the clipboard-only fallback failed")
            self._state.force_idle()
            self._on_result(PipelineResult(kind="injection_failed", text=formatted))
            return

        # The keystroke has been sent; we're done from the app's point of
        # view even though the clipboard-restore timer is still pending.
        self._state.transition(AppState.IDLE)
        if self._history is not None:
            app_name = self._captured_context.app_name if self._captured_context else ""
            self._history.record(formatted, app_name=app_name)
        if self._stats is not None:
            self._stats.record_dictation(len(formatted.split()))
        self._on_result(PipelineResult(kind="injected", text=formatted))

    def _handle_edit_command(self, instruction: str, generation: int) -> None:
        """The 'Edit:'/'Rewrite:' voice command - rewrite whatever's on the
        clipboard per a spoken instruction, then paste the result back."""
        if not self._state.transition(AppState.EDITING):
            return

        try:
            target_text = self._clipboard_reader.paste()
        except Exception:
            logger.exception("Failed to read clipboard for edit command")
            target_text = ""

        if not target_text or not target_text.strip():
            self._on_notify(
                "VoiceFlow",
                "No text on your clipboard to edit - copy something first, then say "
                "\"Edit: ...\" again.",
                NotifyLevel.ERROR,
            )
            self._state.force_idle()
            self._on_result(PipelineResult(kind="ignored_empty"))
            return

        try:
            rewritten = self._formatting.rewrite_text(instruction, target_text)
        except NoProviderConfiguredError as exc:
            self._fail(str(exc), configure_hint=True)
            return
        except AllProvidersFailedError as exc:
            self._fail(f"Couldn't process the edit command: {exc}")
            return
        except Exception:
            logger.exception("Unexpected error during edit/rewrite command")
            self._fail("Couldn't process the edit command unexpectedly.")
            return

        if not self._state.is_current_generation(generation):
            return

        if not self._state.transition(AppState.INJECTING):
            return

        try:
            self._injector.inject(rewritten)
        except InjectionError as exc:
            logger.error("Injection failed after edit command: %s", exc)
            self._on_notify(
                "VoiceFlow",
                "Rewrote it, but couldn't paste automatically - it's on your "
                "clipboard, press Cmd+V to paste it yourself.",
                NotifyLevel.ERROR,
            )
            try:
                PyperclipBackend().copy(rewritten)
            except Exception:
                logger.exception("Even the clipboard-only fallback failed")
            self._state.force_idle()
            self._on_result(PipelineResult(kind="injection_failed", text=rewritten))
            return

        self._state.transition(AppState.IDLE)
        self._on_result(PipelineResult(kind="edited", text=rewritten))

    def _on_generation_idle(self, generation: int) -> None:
        # Purely informational hook point for the restore-completed timer;
        # state is already IDLE by the time this fires.
        logger.debug("Clipboard restored for generation %d", generation)

    def _fail(self, message: str, configure_hint: bool = False) -> None:
        logger.error(message)
        if configure_hint:
            message += " Open VoiceFlow's Settings to add one."
        self._on_notify("VoiceFlow", message, NotifyLevel.ERROR)
        self._state.force_idle()
