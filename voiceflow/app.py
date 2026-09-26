"""The VoiceFlow menu bar application - wires every component together.

This module is macOS-only (it imports ``rumps``). Run it with
``python -m voiceflow.main`` during development, or build it into a real
``.app`` bundle with ``py2app`` (see build_macos_app.sh) for normal use.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
import webbrowser

try:
    import rumps
except ImportError:
    print(
        "ERROR: rumps is not installed, or you're not on macOS.\n"
        "VoiceFlow's menu bar app only runs on macOS. See README.md.",
        file=sys.stderr,
    )
    raise

from voiceflow.logging_setup import configure_logging

# Logging is brought up before anything else in this file imports so that
# even a failure in the "defensively-imported optional features" block
# below - which happens at module-import time - lands in the persistent
# log file, not just stderr (which is invisible once VoiceFlow is a
# double-clicked .app with no attached terminal). configure_logging() is
# idempotent, so run()'s own call to it later is a harmless no-op.
configure_logging()

from voiceflow import __version__
from voiceflow.ai.formatter import FormattingService
from voiceflow.ai.providers import validate_api_key
from voiceflow.ai.transcription import TranscriptionService
from voiceflow.audio.recorder import AudioRecorder
from voiceflow.clipboard.injector import ClipboardInjector, PyperclipBackend
from voiceflow.config import ConfigManager
from voiceflow.context.macos_context import ActiveAppDetector
from voiceflow.hotkeys.listener import DEFAULT_KEY, SUPPORTED_KEYS, GlobalHotkeyListener
from voiceflow.hotkeys.state_machine import HotkeyEvent, HotkeyMode
from voiceflow.memory.store import MemoryStore
from voiceflow.paths import LOG_PATH, MEETING_NOTES_DIR, MEMORY_PATH
from voiceflow.pipeline import MIN_USEFUL_PEAK_AMPLITUDE, DictationPipeline, NotifyLevel, PipelineResult
from voiceflow.state import AppState, StateManager
from voiceflow.ui import launch_agent, onboarding, permissions, sounds

logger = logging.getLogger("voiceflow.app")

GROQ_SIGNUP_URL = "https://console.groq.com/keys"

# ---------------------------------------------------------------------- #
# Defensively-imported optional features.
#
# The core dictation loop above (config, state, pipeline, AI providers,
# clipboard, hotkey) is what actually matters and must never fail to
# import. Everything below is an *enhancement* on top of that loop - if
# any one of these modules ever fails to import for any reason (a
# packaging quirk, a PyObjC/AppKit version mismatch on hud.py, anything),
# the whole app must still launch with that one feature simply missing,
# rather than refusing to start at all. Each failure is logged so it's
# visible in the log file, but never re-raised.
# ---------------------------------------------------------------------- #
try:
    from voiceflow.history import DictationHistory
except Exception:
    logger.exception("DictationHistory unavailable - Recent Dictations will be disabled")
    DictationHistory = None

try:
    from voiceflow.stats import UsageStats
except Exception:
    logger.exception("UsageStats unavailable - the usage stats line will be disabled")
    UsageStats = None

try:
    from voiceflow.meeting import MeetingNotesSession
except Exception:
    logger.exception("MeetingNotesSession unavailable - Meeting Notes will be disabled")
    MeetingNotesSession = None

try:
    from voiceflow.ui.hud import ListeningHUD
except Exception:
    logger.exception("ListeningHUD unavailable - the floating listening indicator will be disabled")
    ListeningHUD = None


class _NullHud:
    """Stand-in used if ListeningHUD couldn't be imported - every call is a no-op."""

    def show(self, text: str) -> None:
        pass

    def hide(self) -> None:
        pass

    def update_text(self, text: str) -> None:
        pass


class _NullHistory:
    """Stand-in used if DictationHistory couldn't be imported."""

    def record(self, text: str, app_name: str = "") -> None:
        pass

    def recent(self, limit: int = 10) -> list:
        return []

    def clear(self) -> None:
        pass

    def count(self) -> int:
        return 0


class _NullStats:
    """Stand-in used if UsageStats couldn't be imported."""

    def record_dictation(self, word_count: int) -> None:
        pass

    def record_fact_learned(self) -> None:
        pass

    def record_meeting(self, word_count: int) -> None:
        pass

    def summary_line(self) -> str:
        return "Usage stats unavailable"


_STATE_TITLES = {
    AppState.IDLE: "🎙",
    AppState.RECORDING: "🔴",
    AppState.TRANSCRIBING: "⏳",
    AppState.FORMATTING: "✍️",
    AppState.INJECTING: "📋",
    AppState.LEARNING: "🧠",
    AppState.EDITING: "🪄",
    AppState.MEETING: "🗒️",
    AppState.ERROR: "⚠️",
}

_HUD_TEXT = {
    AppState.RECORDING: "🎙  Listening...",
    AppState.TRANSCRIBING: "⏳  Transcribing...",
    AppState.FORMATTING: "✍️  Formatting...",
    AppState.INJECTING: "📋  Pasting...",
    AppState.LEARNING: "🧠  Learning...",
    AppState.EDITING: "🪄  Rewriting...",
}

_MODE_LABELS = {
    HotkeyMode.HYBRID: "Hybrid (hold or double-tap)",
    HotkeyMode.HOLD: "Hold-to-talk only",
    HotkeyMode.TOGGLE: "Toggle (tap to start/stop)",
}

_HISTORY_MENU_SLOTS = 8
_HISTORY_PREVIEW_LEN = 46


class VoiceFlowApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("VoiceFlow", title=_STATE_TITLES[AppState.IDLE], quit_button=None)

        self.config = ConfigManager()
        self.state = StateManager()
        self.memory = MemoryStore(max_entries=self.config.get("memory.max_entries", 2000))
        self.history = self._build_optional(
            DictationHistory,
            _NullHistory,
            "history",
            max_entries=self.config.get("history.max_entries", 50),
        )
        self.stats = self._build_optional(UsageStats, _NullStats, "usage stats")
        self.context_detector = ActiveAppDetector()
        self.transcription_service = TranscriptionService(self.config)
        self.formatting_service = FormattingService(self.config)
        self.hud = self._build_optional(ListeningHUD, _NullHud, "listening indicator")

        self.audio_recorder = AudioRecorder(
            sample_rate=self.config.get("audio.sample_rate", 16000),
            channels=self.config.get("audio.channels", 1),
            device=self.config.get("audio.device", None),
            max_recording_seconds=self.config.get("audio.max_recording_seconds", 120),
        )
        self.clipboard_injector = ClipboardInjector(
            restore_delay_ms=self.config.get("clipboard.restore_delay_ms", 250)
        )

        self.pipeline = DictationPipeline(
            config=self.config,
            state=self.state,
            audio_recorder=self.audio_recorder,
            transcription_service=self.transcription_service,
            formatting_service=self.formatting_service,
            memory_store=self.memory,
            clipboard_injector=self.clipboard_injector,
            context_detector=self.context_detector,
            on_notify=self._notify,
            on_result=self._on_pipeline_result,
            history=self.history,
            stats=self.stats,
        )

        self.meeting_session: MeetingNotesSession | None = None
        self._meeting_timer: rumps.Timer | None = None

        self.state.add_listener(self._on_state_change)

        self.hotkey_listener: GlobalHotkeyListener | None = None
        self._build_menu()
        self._start_hotkey_listener()
        self._refresh_history_menu()
        self._refresh_stats_item()

        self._schedule_first_run_check()

    def _build_optional(self, cls, fallback_cls, feature_name: str, **kwargs):
        """Construct an optional-feature object, falling back to a no-op
        stand-in if the real class failed to import OR raises during
        construction - either way, that one feature is disabled instead of
        the whole app failing to launch."""
        if cls is None:
            return fallback_cls()
        try:
            return cls(**kwargs)
        except Exception:
            logger.exception("Failed to initialize %s; disabling that feature", feature_name)
            return fallback_cls()

    # ------------------------------------------------------------------ #
    # Menu construction
    # ------------------------------------------------------------------ #
    def _build_menu(self) -> None:
        self.status_item = rumps.MenuItem("Status: Idle")
        self.toggle_item = rumps.MenuItem("Start Dictation", callback=self._on_toggle_clicked)
        if MeetingNotesSession is not None:
            self.meeting_item = rumps.MenuItem(
                "Start Meeting Notes", callback=self._on_toggle_meeting_notes
            )
        else:
            self.meeting_item = rumps.MenuItem("Meeting Notes (unavailable)", callback=None)

        hotkey_menu = self._build_hotkey_menu()
        providers_menu = self._build_providers_menu()
        memory_menu = self._build_memory_menu()
        history_menu = self._build_history_menu()
        audio_menu = self._build_audio_menu()

        self.stats_item = rumps.MenuItem(self.stats.summary_line())

        self.show_hud_item = rumps.MenuItem(
            "Show Listening Indicator", callback=self._on_toggle_hud
        )
        self.show_hud_item.state = self.config.get("ui.show_hud", True)

        self.launch_at_login_item = rumps.MenuItem(
            "Launch at Login", callback=self._on_toggle_launch_at_login
        )
        self.launch_at_login_item.state = launch_agent.is_enabled()

        self.sound_feedback_item = rumps.MenuItem(
            "Sound Feedback", callback=self._on_toggle_sound_feedback
        )
        self.sound_feedback_item.state = self.config.get("ui.sound_feedback", True)

        self.menu = [
            self.status_item,
            None,
            self.toggle_item,
            self.meeting_item,
            None,
            hotkey_menu,
            providers_menu,
            memory_menu,
            history_menu,
            audio_menu,
            None,
            rumps.MenuItem("Permissions & Setup Guide...", callback=self._on_show_setup_guide),
            rumps.MenuItem("How VoiceFlow Works...", callback=self._on_show_hotkey_help),
            rumps.MenuItem("View Logs", callback=self._on_view_logs),
            None,
            self.stats_item,
            None,
            self.show_hud_item,
            self.sound_feedback_item,
            self.launch_at_login_item,
            None,
            rumps.MenuItem("About VoiceFlow", callback=self._on_about),
            rumps.MenuItem("Quit VoiceFlow", callback=self._on_quit),
        ]

    def _build_hotkey_menu(self) -> "rumps.MenuItem":
        menu = rumps.MenuItem("Hotkey")

        key_menu = rumps.MenuItem("Key")
        current_key = self.config.get("hotkey.key", DEFAULT_KEY)
        self._key_items: dict[str, rumps.MenuItem] = {}
        for key_name, label in SUPPORTED_KEYS.items():
            item = rumps.MenuItem(label, callback=self._make_key_selector(key_name))
            item.state = key_name == current_key
            self._key_items[key_name] = item
            key_menu.add(item)
        menu.add(key_menu)

        mode_menu = rumps.MenuItem("Mode")
        current_mode = self.config.get("hotkey.mode", "hybrid")
        self._mode_items: dict[str, rumps.MenuItem] = {}
        for mode in HotkeyMode:
            item = rumps.MenuItem(_MODE_LABELS[mode], callback=self._make_mode_selector(mode))
            item.state = mode.value == current_mode
            self._mode_items[mode.value] = item
            mode_menu.add(item)
        menu.add(mode_menu)

        return menu

    def _build_providers_menu(self) -> "rumps.MenuItem":
        menu = rumps.MenuItem("AI Providers")
        menu.add(rumps.MenuItem("Quick Setup...", callback=self._on_quick_setup))
        menu.add(None)
        menu.add(rumps.MenuItem("Set Groq API Key...", callback=self._make_key_setter("groq")))
        menu.add(rumps.MenuItem("Set OpenAI API Key...", callback=self._make_key_setter("openai")))
        menu.add(
            rumps.MenuItem("Set Anthropic API Key...", callback=self._make_key_setter("anthropic"))
        )
        menu.add(None)
        self.local_fallback_item = rumps.MenuItem(
            "Enable Offline Fallback (faster-whisper)", callback=self._on_toggle_local_fallback
        )
        self.local_fallback_item.state = "local" in self.config.get(
            "providers.transcription_order", []
        )
        menu.add(self.local_fallback_item)
        return menu

    def _build_memory_menu(self) -> "rumps.MenuItem":
        menu = rumps.MenuItem("Memory")
        menu.add(rumps.MenuItem("Teach VoiceFlow a Fact...", callback=self._on_teach_fact))
        self.memory_count_item = rumps.MenuItem(f"{self.memory.count()} facts learned")
        menu.add(self.memory_count_item)
        menu.add(None)
        menu.add(rumps.MenuItem("Open Memory File", callback=self._on_open_memory_file))
        menu.add(rumps.MenuItem("Clear All Memory...", callback=self._on_clear_memory))
        return menu

    def _build_history_menu(self) -> "rumps.MenuItem":
        menu = rumps.MenuItem("Recent Dictations")
        self._history_items: list[rumps.MenuItem] = []
        for i in range(_HISTORY_MENU_SLOTS):
            # Each placeholder gets a distinct title at insertion time -
            # rumps.MenuItem tracks children by title internally, so two
            # items sharing the same title when added could collide.
            # Updating .title later (in _refresh_history_menu) on an
            # already-added item is a plain attribute mutation and doesn't
            # re-trigger that insertion-time bookkeeping, so it's safe even
            # if two entries end up with identical preview text.
            item = rumps.MenuItem(f"{i + 1}. (empty)", callback=None)
            self._history_items.append(item)
            menu.add(item)
        menu.add(None)
        menu.add(rumps.MenuItem("Clear History", callback=self._on_clear_history))
        return menu

    def _build_audio_menu(self) -> "rumps.MenuItem":
        menu = rumps.MenuItem("Audio")
        input_menu = rumps.MenuItem("Input Device")
        current_device = self.config.get("audio.device", None)

        default_item = rumps.MenuItem(
            "System Default", callback=self._make_device_selector(None)
        )
        default_item.state = current_device is None
        input_menu.add(default_item)

        self._device_items: dict[int, rumps.MenuItem] = {None: default_item}
        try:
            devices = self.audio_recorder.list_input_devices()
        except Exception:
            logger.exception("Failed to list audio input devices")
            devices = []
        for device in devices:
            item = rumps.MenuItem(device["name"], callback=self._make_device_selector(device["index"]))
            item.state = current_device == device["index"]
            self._device_items[device["index"]] = item
            input_menu.add(item)
        menu.add(input_menu)

        self.save_recordings_item = rumps.MenuItem(
            "Save Recordings for Debugging", callback=self._on_toggle_save_recordings
        )
        self.save_recordings_item.state = self.config.get("audio.save_recordings_for_debug", False)
        menu.add(self.save_recordings_item)
        menu.add(None)
        menu.add(rumps.MenuItem("Test Microphone...", callback=self._on_test_microphone))
        return menu

    # ------------------------------------------------------------------ #
    # Hotkey listener lifecycle
    # ------------------------------------------------------------------ #
    def _start_hotkey_listener(self) -> None:
        try:
            self.hotkey_listener = GlobalHotkeyListener(
                key_name=self.config.get("hotkey.key", DEFAULT_KEY),
                mode=HotkeyMode(self.config.get("hotkey.mode", "hybrid")),
                hold_threshold_ms=self.config.get("hotkey.hold_threshold_ms", 180),
                double_tap_window_ms=self.config.get("hotkey.double_tap_window_ms", 350),
                on_event=self._on_hotkey_event,
            )
            self.hotkey_listener.start()
        except Exception:
            logger.exception("Failed to start global hotkey listener")
            self._notify(
                "VoiceFlow",
                "Couldn't start the global hotkey listener. Grant Input Monitoring "
                "access in System Settings, then reopen VoiceFlow. You can still use "
                "the 'Start Dictation' menu item in the meantime.",
                NotifyLevel.ERROR,
            )

    def _restart_hotkey_listener(self) -> None:
        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.stop()
            except Exception:
                logger.exception("Error stopping hotkey listener during reconfigure")
        self._start_hotkey_listener()

    def _on_hotkey_event(self, event: HotkeyEvent) -> None:
        started = event in (
            HotkeyEvent.RECORDING_STARTED_HOLD,
            HotkeyEvent.RECORDING_STARTED_LATCH,
            HotkeyEvent.RECORDING_STARTED_TOGGLE,
        )
        if started:
            if self.config.get("ui.sound_feedback", True):
                sounds.play_start()
            self.pipeline.start_recording()
        else:
            if self.config.get("ui.sound_feedback", True):
                sounds.play_stop()
            self.pipeline.stop_recording()

    # ------------------------------------------------------------------ #
    # Pipeline / state callbacks
    # ------------------------------------------------------------------ #
    def _on_state_change(self, old_state: AppState, new_state: AppState) -> None:
        self.title = _STATE_TITLES.get(new_state, "🎙")
        self.status_item.title = f"Status: {new_state.value.capitalize()}"

        if new_state == AppState.MEETING:
            self.toggle_item.title = "Dictation unavailable (meeting in progress)"
            self.toggle_item.set_callback(None)
        else:
            self.toggle_item.title = (
                "Stop Dictation" if new_state == AppState.RECORDING else
                "Start Dictation" if new_state == AppState.IDLE else "Working..."
            )
            self.toggle_item.set_callback(
                self._on_toggle_clicked if new_state in (AppState.IDLE, AppState.RECORDING) else None
            )

        if self.config.get("ui.show_hud", True):
            if new_state in _HUD_TEXT:
                self.hud.show(_HUD_TEXT[new_state])
            elif new_state in (AppState.IDLE, AppState.ERROR):
                self.hud.hide()

    def _on_pipeline_result(self, result: PipelineResult) -> None:
        if result.kind == "learned":
            self.memory_count_item.title = f"{self.memory.count()} facts learned"
            if self.config.get("ui.sound_feedback", True):
                sounds.play_learned()
        elif result.kind in ("injected", "edited"):
            self._refresh_history_menu()
            self._refresh_stats_item()

    def _notify(self, title: str, message: str, level: str) -> None:
        try:
            rumps.notification(title=title, subtitle="", message=message)
        except Exception:
            logger.exception("Failed to show notification: %s / %s", title, message)
        if level == NotifyLevel.ERROR and self.config.get("ui.sound_feedback", True):
            sounds.play_error()

    def _refresh_stats_item(self) -> None:
        self.stats_item.title = self.stats.summary_line()

    def _refresh_history_menu(self) -> None:
        entries = self.history.recent(_HISTORY_MENU_SLOTS)
        for i, item in enumerate(self._history_items):
            if i < len(entries):
                entry = entries[i]
                preview = entry.text.replace("\n", " ").strip()
                if len(preview) > _HISTORY_PREVIEW_LEN:
                    preview = preview[:_HISTORY_PREVIEW_LEN].rstrip() + "..."
                suffix = f"  ({entry.app_name})" if entry.app_name else ""
                item.title = f"{i + 1}. {preview}{suffix}"
                item.set_callback(self._make_history_copy_handler(entry.text))
            else:
                item.title = f"{i + 1}. (empty)"
                item.set_callback(None)

    def _make_history_copy_handler(self, text: str):
        def _handler(_sender):
            try:
                PyperclipBackend().copy(text)
                self._notify("VoiceFlow", "Copied to clipboard.", NotifyLevel.INFO)
            except Exception:
                logger.exception("Failed to copy history entry to clipboard")

        return _handler

    def _on_clear_history(self, _sender) -> None:
        self.history.clear()
        self._refresh_history_menu()

    # ------------------------------------------------------------------ #
    # Menu callbacks - dictation
    # ------------------------------------------------------------------ #
    def _on_toggle_clicked(self, _sender) -> None:
        if self.state.state == AppState.IDLE:
            self.pipeline.start_recording()
        elif self.state.state == AppState.RECORDING:
            self.pipeline.stop_recording()

    # ------------------------------------------------------------------ #
    # Menu callbacks - Meeting Notes
    # ------------------------------------------------------------------ #
    def _on_toggle_meeting_notes(self, _sender) -> None:
        if self.state.state == AppState.MEETING:
            self._stop_meeting_notes()
        elif self.state.state == AppState.IDLE:
            self._start_meeting_notes()
        else:
            self._notify(
                "VoiceFlow",
                "Finish the current dictation before starting Meeting Notes.",
                NotifyLevel.INFO,
            )

    def _start_meeting_notes(self) -> None:
        if MeetingNotesSession is None:
            self._notify(
                "VoiceFlow", "Meeting Notes isn't available in this build.", NotifyLevel.ERROR
            )
            return

        if not self.state.transition(AppState.MEETING):
            return

        def _recorder_factory():
            return AudioRecorder(
                sample_rate=self.config.get("audio.sample_rate", 16000),
                channels=self.config.get("audio.channels", 1),
                device=self.config.get("audio.device", None),
                max_recording_seconds=self.config.get("meeting.chunk_seconds", 20) + 5,
            )

        try:
            self.meeting_session = MeetingNotesSession(
                audio_recorder_factory=_recorder_factory,
                transcription_service=self.transcription_service,
                formatting_service=self.formatting_service,
                chunk_seconds=self.config.get("meeting.chunk_seconds", 20),
                min_chunk_seconds_to_transcribe=self.config.get(
                    "meeting.min_chunk_seconds_to_transcribe", 1.5
                ),
                generate_summary=self.config.get("meeting.generate_summary", True),
                notes_dir=MEETING_NOTES_DIR,
                on_notify=self._notify,
            )
            file_path = self.meeting_session.start()
        except Exception as exc:
            logger.exception("Failed to start meeting notes session")
            self._notify("VoiceFlow", f"Couldn't start Meeting Notes: {exc}", NotifyLevel.ERROR)
            self.meeting_session = None
            self.state.force_idle()
            return

        self.meeting_item.title = "Stop Meeting Notes"
        self._notify(
            "Meeting Notes started",
            f"Recording continuously. Notes are being saved to {file_path.name}.",
            NotifyLevel.INFO,
        )
        self._meeting_timer = rumps.Timer(self._on_meeting_tick, 1.0)
        self._meeting_timer.start()

    def _stop_meeting_notes(self) -> None:
        if self._meeting_timer is not None:
            self._meeting_timer.stop()
            self._meeting_timer = None

        # Grab and immediately clear the session reference (synchronously,
        # on the main thread) before anything async happens. This is what
        # makes a rapid double-click on "Stop Meeting Notes" safe: the
        # state transition to IDLE only completes later on the background
        # _finish() thread, so without this, a second click landing before
        # that finishes would see state==MEETING and self.meeting_session
        # still set, and spawn a second concurrent _finish() thread against
        # the same session (duplicate summary generation, wasted API call).
        session = self.meeting_session
        self.meeting_session = None
        self.meeting_item.title = "Start Meeting Notes"
        self.hud.hide()

        if session is None:
            self.state.force_idle()
            return

        def _finish():
            try:
                file_path = session.stop()
            except Exception:
                logger.exception("Failed to stop meeting notes session cleanly")
                file_path = session.file_path
            self.stats.record_meeting(session.word_count)
            self._refresh_stats_item()
            self.state.transition(AppState.IDLE)
            if file_path is not None:
                self._notify(
                    "Meeting Notes saved",
                    f"{session.word_count} words captured -> {file_path.name}",
                    NotifyLevel.INFO,
                )
                try:
                    subprocess.run(["open", str(file_path)], check=False)
                except Exception:
                    logger.exception("Failed to open finished meeting notes file")

        threading.Thread(target=_finish, daemon=True, name="voiceflow-meeting-stop").start()

    def _on_meeting_tick(self, _sender) -> None:
        if self.meeting_session is None:
            return
        if not self.meeting_session.is_active:
            # The background loop exited on its own (e.g. a mic error) -
            # tidy up the menu/HUD/state rather than ticking on a dead session.
            self._stop_meeting_notes()
            return
        elapsed = int(self.meeting_session.elapsed_seconds())
        minutes, seconds = divmod(elapsed, 60)
        if self.config.get("ui.show_hud", True):
            self.hud.update_text(f"🗒️  Meeting Notes — {minutes:02d}:{seconds:02d}")
        else:
            self.hud.hide()

    # ------------------------------------------------------------------ #
    # Menu callbacks - hotkey / providers / memory / audio settings
    # ------------------------------------------------------------------ #
    def _make_key_selector(self, key_name: str):
        def _handler(_sender):
            for item in self._key_items.values():
                item.state = False
            self._key_items[key_name].state = True
            self.config.set("hotkey.key", key_name)
            self._restart_hotkey_listener()

        return _handler

    def _make_mode_selector(self, mode: HotkeyMode):
        def _handler(_sender):
            for item in self._mode_items.values():
                item.state = False
            self._mode_items[mode.value].state = True
            self.config.set("hotkey.mode", mode.value)
            self._restart_hotkey_listener()

        return _handler

    def _on_quick_setup(self, _sender) -> None:
        rumps.alert(
            title="VoiceFlow Quick Setup",
            message=onboarding.NO_PROVIDER_MESSAGE,
            ok="Continue",
        )
        try:
            webbrowser.open(GROQ_SIGNUP_URL)
        except Exception:
            logger.exception("Failed to open browser for Groq signup")
        self._prompt_and_save_key("groq")

    def _make_key_setter(self, provider: str):
        def _handler(_sender):
            self._prompt_and_save_key(provider)

        return _handler

    def _prompt_and_save_key(self, provider: str) -> None:
        current = self.config.get(f"providers.{provider}_api_key", "")
        masked = ("•" * min(len(current), 20)) if current else ""
        window = rumps.Window(
            message=f"Paste your {provider.capitalize()} API key below. It's stored locally "
            f"in ~/Library/Application Support/VoiceFlow/config.json and never leaves "
            f"your machine except to call {provider.capitalize()}'s API directly.",
            title=f"{provider.capitalize()} API Key",
            default_text=masked,
            ok="Save",
            cancel="Cancel",
            dimensions=(320, 22),
        )
        response = window.run()
        # Deliberately gate on "is there real, different text" rather than
        # response.clicked - a save this cheap and reversible is safer to
        # err toward doing than toward silently discarding a key the user
        # actually typed in, if some button-index assumption turns out to
        # be wrong for a given rumps/macOS version.
        key = (response.text or "").strip()
        if not key or key == masked:
            return
        self.config.set(f"providers.{provider}_api_key", key)
        self._notify("VoiceFlow", f"{provider.capitalize()} key saved - verifying...", NotifyLevel.INFO)

        def _validate():
            ok, message = validate_api_key(provider, key)
            level = NotifyLevel.INFO if ok else NotifyLevel.ERROR
            self._notify(f"{provider.capitalize()} API Key", message, level)

        threading.Thread(target=_validate, daemon=True, name="voiceflow-key-validate").start()

    def _on_toggle_local_fallback(self, sender) -> None:
        order = self.config.get("providers.transcription_order", [])
        if "local" in order:
            order = [p for p in order if p != "local"]
            sender.state = False
        else:
            order = order + ["local"]
            sender.state = True
        self.config.set("providers.transcription_order", order)

    def _on_teach_fact(self, _sender) -> None:
        window = rumps.Window(
            message="What should VoiceFlow remember? (e.g. 'My boss's name is Sarah Chen')",
            title="Teach VoiceFlow a Fact",
            ok="Learn",
            cancel="Cancel",
            dimensions=(320, 22),
        )
        response = window.run()
        # See _prompt_and_save_key for why this doesn't gate on response.clicked.
        statement = (response.text or "").strip()
        if not statement:
            return

        def _run():
            try:
                facts = self.formatting_service.extract_facts(statement)
                added = self.memory.learn_from_facts(facts)
            except Exception as exc:
                logger.exception("Manual fact extraction failed")
                self._notify("VoiceFlow", f"Couldn't process that: {exc}", NotifyLevel.ERROR)
                return
            for _ in added:
                self.stats.record_fact_learned()
            self._on_pipeline_result(PipelineResult(kind="learned", learned_count=len(added)))
            if added:
                self._notify(
                    "VoiceFlow learned something new",
                    "; ".join(f"[{e.category}] {e.text}" for e in added[:3]),
                    NotifyLevel.INFO,
                )
            else:
                self._notify("VoiceFlow", "Didn't find a clear fact in that.", NotifyLevel.INFO)

        threading.Thread(target=_run, daemon=True, name="voiceflow-teach-fact").start()

    def _on_open_memory_file(self, _sender) -> None:
        subprocess.run(["open", str(MEMORY_PATH)], check=False)

    def _on_clear_memory(self, _sender) -> None:
        if rumps.alert(
            title="Clear All Memory?",
            message="This permanently deletes everything VoiceFlow has learned about you. "
            "This can't be undone.",
            ok="Clear Everything",
            cancel="Cancel",
        ) == 1:
            for entry in self.memory.all_entries():
                self.memory.delete_entry(entry.id)
            self.memory_count_item.title = f"{self.memory.count()} facts learned"

    def _make_device_selector(self, device_index):
        def _handler(_sender):
            for item in self._device_items.values():
                item.state = False
            self._device_items[device_index].state = True
            self.config.set("audio.device", device_index)
            self.audio_recorder = AudioRecorder(
                sample_rate=self.config.get("audio.sample_rate", 16000),
                channels=self.config.get("audio.channels", 1),
                device=device_index,
                max_recording_seconds=self.config.get("audio.max_recording_seconds", 120),
            )
            self.pipeline._audio = self.audio_recorder

        return _handler

    def _on_toggle_save_recordings(self, sender) -> None:
        new_value = not self.config.get("audio.save_recordings_for_debug", False)
        sender.state = new_value
        self.config.set("audio.save_recordings_for_debug", new_value)

    def _on_test_microphone(self, _sender) -> None:
        """Isolated audio round-trip, independent of AI keys/hotkey/permissions
        for anything else - the fastest way to tell whether the microphone
        itself (and macOS's permission for it) is actually working, and to
        surface the exact error if it isn't. Uses its own throwaway
        AudioRecorder rather than self.audio_recorder so it can never
        collide with a real dictation in progress."""
        if self.state.state != AppState.IDLE:
            self._notify(
                "VoiceFlow", "Finish the current action before testing the microphone.", NotifyLevel.INFO
            )
            return

        self._notify("VoiceFlow", "Testing microphone for 1.5 seconds - say something...", NotifyLevel.INFO)

        def _run():
            test_recorder = AudioRecorder(
                sample_rate=self.config.get("audio.sample_rate", 16000),
                channels=self.config.get("audio.channels", 1),
                device=self.config.get("audio.device", None),
                max_recording_seconds=5,
            )
            try:
                test_recorder.start()
            except Exception as exc:
                logger.exception("Microphone test failed to start")
                self._notify("Microphone Test Failed", str(exc), NotifyLevel.ERROR)
                return

            time.sleep(1.5)

            try:
                result = test_recorder.stop()
            except Exception as exc:
                logger.exception("Microphone test failed to stop")
                self._notify("Microphone Test Failed", str(exc), NotifyLevel.ERROR)
                return

            if result.peak_amplitude < MIN_USEFUL_PEAK_AMPLITUDE:
                self._notify(
                    "Microphone Test",
                    f"Opened the microphone fine, but heard near-silence (peak level "
                    f"{result.peak_amplitude:.3f}). Check System Settings -> Privacy & "
                    f"Security -> Microphone (VoiceFlow must be checked), and that the "
                    f"right input device is selected under Audio -> Input Device.",
                    NotifyLevel.ERROR,
                )
            else:
                self._notify(
                    "Microphone Test Passed",
                    f"Heard you clearly (peak level {result.peak_amplitude:.2f}). "
                    f"Your microphone is working.",
                    NotifyLevel.INFO,
                )

        threading.Thread(target=_run, daemon=True, name="voiceflow-mic-test").start()

    def _on_toggle_sound_feedback(self, sender) -> None:
        new_value = not self.config.get("ui.sound_feedback", True)
        sender.state = new_value
        self.config.set("ui.sound_feedback", new_value)

    def _on_toggle_hud(self, sender) -> None:
        new_value = not self.config.get("ui.show_hud", True)
        sender.state = new_value
        self.config.set("ui.show_hud", new_value)
        if not new_value:
            self.hud.hide()

    def _on_toggle_launch_at_login(self, sender) -> None:
        app_path = sys.executable
        # When bundled by py2app, sys.executable points inside VoiceFlow.app/Contents/MacOS/.
        # Walk up to the .app bundle itself for the LaunchAgent to open.
        marker = ".app/Contents/MacOS"
        if marker in app_path:
            app_path = app_path.split(marker)[0] + ".app"

        if launch_agent.is_enabled():
            launch_agent.disable()
            sender.state = False
        else:
            ok = launch_agent.enable(app_path)
            sender.state = ok
            if not ok:
                self._notify("VoiceFlow", "Couldn't enable launch at login.", NotifyLevel.ERROR)

    def _on_show_setup_guide(self, _sender) -> None:
        rumps.alert(title="VoiceFlow Setup", message=onboarding.WELCOME_MESSAGE, ok="Open Microphone Settings")
        permissions.open_microphone_settings()
        permissions.open_accessibility_settings()
        permissions.open_input_monitoring_settings()

    def _on_show_hotkey_help(self, _sender) -> None:
        rumps.alert(title="How VoiceFlow Works", message=onboarding.HOTKEY_HELP, ok="Got it")

    def _on_view_logs(self, _sender) -> None:
        subprocess.run(["open", str(LOG_PATH)], check=False)

    def _on_about(self, _sender) -> None:
        rumps.alert(
            title="VoiceFlow",
            message=f"Version {__version__}\n\nA hyper-personalized, context-aware voice "
            "dictation assistant that lives in your menu bar.",
            ok="OK",
        )

    def _on_quit(self, _sender) -> None:
        try:
            if self.hotkey_listener is not None:
                self.hotkey_listener.stop()
        except Exception:
            logger.exception("Error stopping hotkey listener on quit")
        try:
            if self._meeting_timer is not None:
                self._meeting_timer.stop()
            if self.meeting_session is not None and self.meeting_session.is_active:
                self.meeting_session.stop()
        except Exception:
            logger.exception("Error stopping meeting notes session on quit")
        rumps.quit_application()

    # ------------------------------------------------------------------ #
    # First-run onboarding
    #
    # IMPORTANT: this must never be able to block the app or loop. An
    # earlier version used a repeating rumps.Timer as if it were a one-shot
    # delay and paired it with a blocking modal rumps.alert() - since the
    # timer actually fires every interval forever until explicitly stopped,
    # it kept reopening the alert the instant it was dismissed, making the
    # app unusable. Fixed by (a) stopping the timer the first time it
    # fires, so it only ever runs once, and (b) using a passive, non-
    # blocking notification here instead of a modal alert, so even if this
    # logic had a bug again it could never trap anyone in a dialog loop.
    # ------------------------------------------------------------------ #
    def _schedule_first_run_check(self) -> None:
        self._first_run_timer = rumps.Timer(self._on_first_run_timer_fired, 1.5)
        self._first_run_timer.start()

    def _on_first_run_timer_fired(self, sender) -> None:
        sender.stop()
        if self.config.get("ui.onboarding_shown", False):
            return
        self.config.set("ui.onboarding_shown", True)
        if not self.config.has_any_provider_configured():
            self._notify("Welcome to VoiceFlow 👋", onboarding.QUICK_SETUP_NOTIFICATION, NotifyLevel.INFO)


def run() -> None:
    configure_logging()
    logger.info("Starting VoiceFlow %s", __version__)
    app = VoiceFlowApp()
    app.run()
