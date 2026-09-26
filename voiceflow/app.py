"""The VoiceFlow menu bar application - wires every component together.

This module is macOS-only (it imports ``rumps``). Run it with
``python -m voiceflow.main`` during development, or build it into a real
``.app`` bundle with ``py2app`` (see build_macos_app.sh) for normal use.
"""

from __future__ import annotations

import logging
import sys

try:
    import rumps
except ImportError:
    print(
        "ERROR: rumps is not installed, or you're not on macOS.\n"
        "VoiceFlow's menu bar app only runs on macOS. See README.md.",
        file=sys.stderr,
    )
    raise

from voiceflow import __version__
from voiceflow.ai.formatter import FormattingService
from voiceflow.ai.transcription import TranscriptionService
from voiceflow.audio.recorder import AudioRecorder
from voiceflow.clipboard.injector import ClipboardInjector
from voiceflow.config import ConfigManager
from voiceflow.context.macos_context import ActiveAppDetector
from voiceflow.hotkeys.listener import DEFAULT_KEY, SUPPORTED_KEYS, GlobalHotkeyListener
from voiceflow.hotkeys.state_machine import HotkeyEvent, HotkeyMode
from voiceflow.logging_setup import configure_logging
from voiceflow.memory.store import MemoryStore
from voiceflow.paths import LOG_PATH, MEMORY_PATH
from voiceflow.pipeline import DictationPipeline, NotifyLevel, PipelineResult
from voiceflow.state import AppState, StateManager
from voiceflow.ui import launch_agent, onboarding, permissions, sounds

logger = logging.getLogger("voiceflow.app")

_STATE_TITLES = {
    AppState.IDLE: "🎙",
    AppState.RECORDING: "🔴",
    AppState.TRANSCRIBING: "⏳",
    AppState.FORMATTING: "✍️",
    AppState.INJECTING: "📋",
    AppState.LEARNING: "🧠",
    AppState.ERROR: "⚠️",
}

_MODE_LABELS = {
    HotkeyMode.HYBRID: "Hybrid (hold or double-tap)",
    HotkeyMode.HOLD: "Hold-to-talk only",
    HotkeyMode.TOGGLE: "Toggle (tap to start/stop)",
}


class VoiceFlowApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("VoiceFlow", title=_STATE_TITLES[AppState.IDLE], quit_button=None)

        self.config = ConfigManager()
        self.state = StateManager()
        self.memory = MemoryStore(max_entries=self.config.get("memory.max_entries", 2000))
        self.context_detector = ActiveAppDetector()
        self.transcription_service = TranscriptionService(self.config)
        self.formatting_service = FormattingService(self.config)

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
        )

        self.state.add_listener(self._on_state_change)

        self.hotkey_listener: GlobalHotkeyListener | None = None
        self._build_menu()
        self._start_hotkey_listener()

        if not self.config.has_any_provider_configured():
            rumps.Timer(lambda _t: self._first_run_prompt(), 1.0).start()

    # ------------------------------------------------------------------ #
    # Menu construction
    # ------------------------------------------------------------------ #
    def _build_menu(self) -> None:
        self.status_item = rumps.MenuItem("Status: Idle")
        self.toggle_item = rumps.MenuItem("Start Dictation", callback=self._on_toggle_clicked)

        hotkey_menu = self._build_hotkey_menu()
        providers_menu = self._build_providers_menu()
        memory_menu = self._build_memory_menu()
        audio_menu = self._build_audio_menu()

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
            None,
            hotkey_menu,
            providers_menu,
            memory_menu,
            audio_menu,
            None,
            rumps.MenuItem("Permissions & Setup Guide...", callback=self._on_show_setup_guide),
            rumps.MenuItem("How Hotkeys Work...", callback=self._on_show_hotkey_help),
            rumps.MenuItem("View Logs", callback=self._on_view_logs),
            None,
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
    # Pipeline callbacks
    # ------------------------------------------------------------------ #
    def _on_state_change(self, old_state: AppState, new_state: AppState) -> None:
        self.title = _STATE_TITLES.get(new_state, "🎙")
        self.status_item.title = f"Status: {new_state.value.capitalize()}"
        self.toggle_item.title = "Stop Dictation" if new_state == AppState.RECORDING else (
            "Start Dictation" if new_state == AppState.IDLE else "Working..."
        )
        self.toggle_item.set_callback(
            self._on_toggle_clicked if new_state in (AppState.IDLE, AppState.RECORDING) else None
        )

    def _on_pipeline_result(self, result: PipelineResult) -> None:
        if result.kind == "learned":
            self.memory_count_item.title = f"{self.memory.count()} facts learned"
            if self.config.get("ui.sound_feedback", True):
                sounds.play_learned()

    def _notify(self, title: str, message: str, level: str) -> None:
        try:
            rumps.notification(title=title, subtitle="", message=message)
        except Exception:
            logger.exception("Failed to show notification: %s / %s", title, message)
        if level == NotifyLevel.ERROR and self.config.get("ui.sound_feedback", True):
            sounds.play_error()

    # ------------------------------------------------------------------ #
    # Menu callbacks
    # ------------------------------------------------------------------ #
    def _on_toggle_clicked(self, _sender) -> None:
        if self.state.state == AppState.IDLE:
            self.pipeline.start_recording()
        elif self.state.state == AppState.RECORDING:
            self.pipeline.stop_recording()

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

    def _make_key_setter(self, provider: str):
        def _handler(_sender):
            current = self.config.get(f"providers.{provider}_api_key", "")
            masked = ("•" * min(len(current), 20)) if current else ""
            window = rumps.Window(
                message=f"Enter your {provider.capitalize()} API key. It's stored locally "
                f"in ~/Library/Application Support/VoiceFlow/config.json and never leaves "
                f"your machine except to call {provider.capitalize()}'s API directly.",
                title=f"{provider.capitalize()} API Key",
                default_text=masked,
                ok="Save",
                cancel="Cancel",
                dimensions=(320, 22),
            )
            try:
                window.icon = None
            except Exception:
                pass
            response = window.run()
            if response.clicked and response.text and response.text != masked:
                self.config.set(f"providers.{provider}_api_key", response.text.strip())
                self._notify("VoiceFlow", f"{provider.capitalize()} API key saved.", NotifyLevel.INFO)

        return _handler

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
        if not (response.clicked and response.text.strip()):
            return

        statement = response.text.strip()

        def _run():
            try:
                facts = self.formatting_service.extract_facts(statement)
                added = self.memory.learn_from_facts(facts)
            except Exception as exc:
                logger.exception("Manual fact extraction failed")
                self._notify("VoiceFlow", f"Couldn't process that: {exc}", NotifyLevel.ERROR)
                return
            self._on_pipeline_result(PipelineResult(kind="learned", learned_count=len(added)))
            if added:
                self._notify(
                    "VoiceFlow learned something new",
                    "; ".join(f"[{e.category}] {e.text}" for e in added[:3]),
                    NotifyLevel.INFO,
                )
            else:
                self._notify("VoiceFlow", "Didn't find a clear fact in that.", NotifyLevel.INFO)

        import threading

        threading.Thread(target=_run, daemon=True).start()

    def _on_open_memory_file(self, _sender) -> None:
        import subprocess

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

    def _on_toggle_sound_feedback(self, sender) -> None:
        new_value = not self.config.get("ui.sound_feedback", True)
        sender.state = new_value
        self.config.set("ui.sound_feedback", new_value)

    def _on_toggle_launch_at_login(self, sender) -> None:
        import sys as _sys

        app_path = _sys.executable
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
        rumps.alert(title="How VoiceFlow's Hotkey Works", message=onboarding.HOTKEY_HELP, ok="Got it")

    def _on_view_logs(self, _sender) -> None:
        import subprocess

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
        rumps.quit_application()

    def _first_run_prompt(self) -> None:
        rumps.alert(title="Welcome to VoiceFlow", message=onboarding.NO_PROVIDER_MESSAGE, ok="OK")


def run() -> None:
    configure_logging()
    logger.info("Starting VoiceFlow %s", __version__)
    app = VoiceFlowApp()
    app.run()
