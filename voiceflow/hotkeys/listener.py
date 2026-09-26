"""macOS global hotkey listener - thin ``pynput`` adapter over ``HotkeyStateMachine``.

Requires the "Input Monitoring" and "Accessibility" permissions to be
granted to VoiceFlow (or your terminal, while running from source) in
System Settings -> Privacy & Security. See the onboarding window for the
guided flow.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from voiceflow.hotkeys.state_machine import (
    HotkeyConfig,
    HotkeyEvent,
    HotkeyMode,
    HotkeyStateMachine,
)
from voiceflow.utils.scheduler import ThreadingScheduler

logger = logging.getLogger("voiceflow.hotkeys.listener")

try:
    from pynput import keyboard as _pynput_keyboard
except ImportError:  # pragma: no cover - exercised only off-macOS
    _pynput_keyboard = None


# Human-friendly names shown in Settings, mapped to pynput Key members.
# Right-side modifier keys and function keys are preferred defaults because
# they rarely collide with normal typing and (unlike Caps Lock) don't carry
# OS-level toggle-state side effects.
SUPPORTED_KEYS: dict[str, str] = {
    "alt_r": "Right Option (⌥)",
    "alt_l": "Left Option (⌥)",
    "cmd_r": "Right Command (⌘)",
    "ctrl_r": "Right Control",
    "shift_r": "Right Shift",
    "caps_lock": "Caps Lock",
    "f13": "F13",
    "f14": "F14",
    "f15": "F15",
    "f16": "F16",
    "f17": "F17",
    "f18": "F18",
    "f19": "F19",
}

DEFAULT_KEY = "alt_r"


def _resolve_key(key_name: str):
    if _pynput_keyboard is None:
        return None
    if key_name not in SUPPORTED_KEYS:
        logger.warning("Unknown hotkey %r, falling back to %r", key_name, DEFAULT_KEY)
        key_name = DEFAULT_KEY
    return getattr(_pynput_keyboard.Key, key_name)


class GlobalHotkeyListener:
    """Owns a ``pynput.keyboard.Listener`` and a ``HotkeyStateMachine``.

    ``on_event`` is invoked (from the pynput listener thread, or a timer
    thread for hybrid-mode threshold callbacks) with a ``HotkeyEvent``.
    Consumers should treat that callback as "not the main thread" and hop
    back onto whatever thread they need.
    """

    def __init__(
        self,
        key_name: str,
        mode: HotkeyMode,
        hold_threshold_ms: float,
        double_tap_window_ms: float,
        on_event: Callable[[HotkeyEvent], None],
    ) -> None:
        if _pynput_keyboard is None:
            raise RuntimeError(
                "pynput is not installed / not usable on this platform. "
                "GlobalHotkeyListener only runs on macOS with pynput installed."
            )
        self._on_event = on_event
        self._target_key = _resolve_key(key_name)
        self._machine = HotkeyStateMachine(
            HotkeyConfig(
                mode=mode,
                hold_threshold_ms=hold_threshold_ms,
                double_tap_window_ms=double_tap_window_ms,
            ),
            on_event=on_event,
            scheduler=ThreadingScheduler(),
        )
        self._listener: Optional["_pynput_keyboard.Listener"] = None
        self._key_currently_down = False

    def reconfigure(
        self, key_name: str, mode: HotkeyMode, hold_threshold_ms: float, double_tap_window_ms: float
    ) -> None:
        """Apply new settings without requiring an app restart."""
        self._target_key = _resolve_key(key_name)
        self._key_currently_down = False
        self._machine = HotkeyStateMachine(
            HotkeyConfig(
                mode=mode,
                hold_threshold_ms=hold_threshold_ms,
                double_tap_window_ms=double_tap_window_ms,
            ),
            on_event=self._on_event,
            scheduler=ThreadingScheduler(),
        )

    def _on_press(self, key) -> None:
        if key == self._target_key and not self._key_currently_down:
            self._key_currently_down = True
            try:
                self._machine.key_down()
            except Exception:
                logger.exception("Error handling key_down")

    def _on_release(self, key) -> None:
        if key == self._target_key:
            self._key_currently_down = False
            try:
                self._machine.key_up()
            except Exception:
                logger.exception("Error handling key_up")

    def start(self) -> None:
        self._listener = _pynput_keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()
        logger.info("Global hotkey listener started")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
        self._machine.reset()
        logger.info("Global hotkey listener stopped")

    def force_reset(self) -> None:
        """Cancel any in-flight hold/double-tap timers (used after an error)."""
        self._machine.reset()
        self._key_currently_down = False
