"""Pure-logic hotkey interaction state machine.

This is deliberately kept free of any OS/keyboard-library dependency so it
can be unit tested deterministically on any platform (including this
Linux dev sandbox). The real global-hotkey listener
(``voiceflow.hotkeys.listener``) is a thin adapter that feeds real
press/release events from ``pynput`` into this class and schedules real
timers for it.

Supported interaction modes (configurable, see voiceflow/config.py):

  * ``HOLD``   - classic push-to-talk. Press = start recording,
                 release = stop & process. No double-tap behavior.
  * ``TOGGLE`` - press once to start, press again to stop. Duration of
                 each press is irrelevant.
  * ``HYBRID`` - the Wispr-Flow-like default:
                   - hold the key past ``hold_threshold_ms`` -> start
                     "held" recording; release -> stop & process.
                   - a quick tap (press+release under the threshold)
                     followed by a second quick tap within
                     ``double_tap_window_ms`` -> starts "latched" hands-free
                     recording that keeps going after you let go.
                   - while latched, the same double-tap gesture stops it
                     and sends it off for processing. A lone tap (no
                     follow-up second tap) is a no-op in both cases, so
                     accidental brushes of the key don't do anything.
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from voiceflow.utils.scheduler import CancelHandle, Scheduler, ThreadingScheduler

logger = logging.getLogger("voiceflow.hotkeys")


class HotkeyMode(enum.Enum):
    HOLD = "hold"
    TOGGLE = "toggle"
    HYBRID = "hybrid"


class HotkeyEvent(enum.Enum):
    """Emitted to the owning application via the ``on_event`` callback."""

    RECORDING_STARTED_HOLD = "recording_started_hold"
    RECORDING_STARTED_LATCH = "recording_started_latch"
    RECORDING_STARTED_TOGGLE = "recording_started_toggle"
    RECORDING_STOPPED_RELEASE = "recording_stopped_release"
    RECORDING_STOPPED_LATCH = "recording_stopped_latch"
    RECORDING_STOPPED_TOGGLE = "recording_stopped_toggle"


class _MachineState(enum.Enum):
    IDLE = "idle"
    DOWN_PENDING = "down_pending"  # key down, deciding tap vs hold
    HELD_RECORDING = "held_recording"
    WAITING_TAP2 = "waiting_tap2"  # released quickly, waiting for a 2nd tap
    LATCHED_RECORDING = "latched_recording"
    LATCHED_DOWN_PENDING = "latched_down_pending"
    LATCHED_WAITING_TAP2 = "latched_waiting_tap2"


@dataclass
class HotkeyConfig:
    mode: HotkeyMode = HotkeyMode.HYBRID
    hold_threshold_ms: float = 180.0
    double_tap_window_ms: float = 350.0


class HotkeyStateMachine:
    """Consumes ``key_down()`` / ``key_up()`` and emits ``HotkeyEvent``s.

    Thread-safety: all public methods acquire an internal lock, since
    real key events arrive on the OS listener thread while timer callbacks
    fire on separate timer threads.
    """

    def __init__(
        self,
        config: HotkeyConfig,
        on_event: Callable[[HotkeyEvent], None],
        scheduler: Optional[Scheduler] = None,
    ) -> None:
        self._config = config
        self._on_event = on_event
        self._scheduler = scheduler or ThreadingScheduler()
        self._state = _MachineState.IDLE
        self._lock = threading.RLock()
        self._pending_timer: Optional[CancelHandle] = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state.value

    def reset(self) -> None:
        """Force back to IDLE, cancelling any pending timers. Used on errors."""
        with self._lock:
            self._cancel_pending_locked()
            self._state = _MachineState.IDLE

    def _cancel_pending_locked(self) -> None:
        if self._pending_timer is not None:
            self._pending_timer.cancel()
            self._pending_timer = None

    def _emit(self, event: HotkeyEvent) -> None:
        try:
            self._on_event(event)
        except Exception:
            logger.exception("Hotkey event handler raised for %s", event)

    # ------------------------------------------------------------------ #
    # Public event entry points - called from the real listener thread
    # ------------------------------------------------------------------ #
    def key_down(self) -> None:
        with self._lock:
            if self._config.mode == HotkeyMode.HOLD:
                self._down_hold_mode_locked()
            elif self._config.mode == HotkeyMode.TOGGLE:
                self._down_toggle_mode_locked()
            else:
                self._down_hybrid_mode_locked()

    def key_up(self) -> None:
        with self._lock:
            if self._config.mode == HotkeyMode.HOLD:
                self._up_hold_mode_locked()
            elif self._config.mode == HotkeyMode.TOGGLE:
                pass  # toggle mode only reacts to key_down
            else:
                self._up_hybrid_mode_locked()

    # ------------------------------------------------------------------ #
    # HOLD mode
    # ------------------------------------------------------------------ #
    def _down_hold_mode_locked(self) -> None:
        if self._state == _MachineState.IDLE:
            self._state = _MachineState.HELD_RECORDING
            self._emit(HotkeyEvent.RECORDING_STARTED_HOLD)

    def _up_hold_mode_locked(self) -> None:
        if self._state == _MachineState.HELD_RECORDING:
            self._state = _MachineState.IDLE
            self._emit(HotkeyEvent.RECORDING_STOPPED_RELEASE)

    # ------------------------------------------------------------------ #
    # TOGGLE mode
    # ------------------------------------------------------------------ #
    def _down_toggle_mode_locked(self) -> None:
        if self._state == _MachineState.IDLE:
            self._state = _MachineState.LATCHED_RECORDING
            self._emit(HotkeyEvent.RECORDING_STARTED_TOGGLE)
        elif self._state == _MachineState.LATCHED_RECORDING:
            self._state = _MachineState.IDLE
            self._emit(HotkeyEvent.RECORDING_STOPPED_TOGGLE)

    # ------------------------------------------------------------------ #
    # HYBRID mode
    # ------------------------------------------------------------------ #
    def _down_hybrid_mode_locked(self) -> None:
        if self._state == _MachineState.IDLE:
            self._state = _MachineState.DOWN_PENDING
            self._pending_timer = self._scheduler.schedule(
                self._config.hold_threshold_ms, self._on_hold_threshold_elapsed
            )

        elif self._state == _MachineState.WAITING_TAP2:
            # Second tap arrived in time -> confirmed double tap -> start latch
            self._cancel_pending_locked()
            self._state = _MachineState.LATCHED_RECORDING
            self._emit(HotkeyEvent.RECORDING_STARTED_LATCH)

        elif self._state == _MachineState.LATCHED_RECORDING:
            self._state = _MachineState.LATCHED_DOWN_PENDING
            self._pending_timer = self._scheduler.schedule(
                self._config.hold_threshold_ms, self._on_latched_hold_threshold_elapsed
            )

        elif self._state == _MachineState.LATCHED_WAITING_TAP2:
            # Second tap while latched -> confirmed double tap -> stop latch
            self._cancel_pending_locked()
            self._state = _MachineState.IDLE
            self._emit(HotkeyEvent.RECORDING_STOPPED_LATCH)

        # DOWN_PENDING / HELD_RECORDING / LATCHED_DOWN_PENDING: key is
        # physically already down, a duplicate down event is ignored.

    def _up_hybrid_mode_locked(self) -> None:
        if self._state == _MachineState.DOWN_PENDING:
            # Released before the hold threshold -> this was a tap.
            self._cancel_pending_locked()
            self._state = _MachineState.WAITING_TAP2
            self._pending_timer = self._scheduler.schedule(
                self._config.double_tap_window_ms, self._on_double_tap_window_elapsed
            )

        elif self._state == _MachineState.HELD_RECORDING:
            self._state = _MachineState.IDLE
            self._emit(HotkeyEvent.RECORDING_STOPPED_RELEASE)

        elif self._state == _MachineState.LATCHED_DOWN_PENDING:
            self._cancel_pending_locked()
            self._state = _MachineState.LATCHED_WAITING_TAP2
            self._pending_timer = self._scheduler.schedule(
                self._config.double_tap_window_ms, self._on_latched_double_tap_window_elapsed
            )

        # WAITING_TAP2 / IDLE / LATCHED_RECORDING / LATCHED_WAITING_TAP2:
        # a key_up with no matching pending press is ignored.

    # ------------------------------------------------------------------ #
    # Timer callbacks (fire on a scheduler thread, not the listener thread)
    # ------------------------------------------------------------------ #
    def _on_hold_threshold_elapsed(self) -> None:
        with self._lock:
            if self._state != _MachineState.DOWN_PENDING:
                return  # key was already released; irrelevant now
            self._pending_timer = None
            self._state = _MachineState.HELD_RECORDING
            self._emit(HotkeyEvent.RECORDING_STARTED_HOLD)

    def _on_double_tap_window_elapsed(self) -> None:
        with self._lock:
            if self._state != _MachineState.WAITING_TAP2:
                return
            self._pending_timer = None
            self._state = _MachineState.IDLE  # lone tap - no-op

    def _on_latched_hold_threshold_elapsed(self) -> None:
        with self._lock:
            if self._state != _MachineState.LATCHED_DOWN_PENDING:
                return
            self._pending_timer = None
            # A plain hold while already latched does not stop recording;
            # only the double-tap gesture does. Fall back to latched-idle.
            self._state = _MachineState.LATCHED_RECORDING

    def _on_latched_double_tap_window_elapsed(self) -> None:
        with self._lock:
            if self._state != _MachineState.LATCHED_WAITING_TAP2:
                return
            self._pending_timer = None
            self._state = _MachineState.LATCHED_RECORDING  # lone tap - no-op
