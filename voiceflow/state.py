"""Thread-safe application state machine.

The recording pipeline runs across several threads (hotkey listener thread,
audio callback thread, network I/O thread, main UI thread), so the current
state needs a single source of truth that any of them can read/update
safely, plus an observer hook the menu bar UI uses to update its icon/title
without polling.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("voiceflow.state")


class AppState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    FORMATTING = "formatting"
    INJECTING = "injecting"
    LEARNING = "learning"
    ERROR = "error"

    @property
    def is_busy(self) -> bool:
        return self not in (AppState.IDLE, AppState.ERROR)


# States it is legal to transition *into* from a given state. This prevents
# e.g. an in-flight network response from clobbering a state that has
# already moved on (a stale TRANSCRIBING->FORMATTING transition arriving
# after the user already cancelled back to IDLE).
_ALLOWED_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.IDLE: {AppState.RECORDING, AppState.ERROR},
    AppState.RECORDING: {AppState.TRANSCRIBING, AppState.IDLE, AppState.ERROR},
    AppState.TRANSCRIBING: {
        AppState.FORMATTING,
        AppState.LEARNING,
        AppState.IDLE,
        AppState.ERROR,
    },
    AppState.FORMATTING: {AppState.INJECTING, AppState.IDLE, AppState.ERROR},
    AppState.LEARNING: {AppState.IDLE, AppState.ERROR},
    AppState.INJECTING: {AppState.IDLE, AppState.ERROR},
    AppState.ERROR: {AppState.IDLE, AppState.RECORDING},
}

StateListener = Callable[[AppState, AppState], None]


@dataclass
class _Generation:
    """Monotonic counter used to invalidate stale async pipeline runs.

    Every time a new recording starts we bump the generation. Any callback
    from a previous generation (e.g. a slow API call for a recording the
    user already cancelled) checks its captured generation against the
    current one and no-ops if they differ.
    """

    value: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump(self) -> int:
        with self.lock:
            self.value += 1
            return self.value

    def current(self) -> int:
        with self.lock:
            return self.value


class StateManager:
    """The single source of truth for what VoiceFlow is currently doing."""

    def __init__(self) -> None:
        self._state = AppState.IDLE
        self._lock = threading.RLock()
        self._listeners: list[StateListener] = []
        self._generation = _Generation()
        self._last_transition_ts = time.monotonic()

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def generation(self) -> int:
        return self._generation.current()

    def new_generation(self) -> int:
        """Call when starting a new recording; returns the id to tag async work with."""
        return self._generation.bump()

    def is_current_generation(self, generation: int) -> bool:
        return generation == self._generation.current()

    def transition(self, new_state: AppState, *, force: bool = False) -> bool:
        """Attempt to move to ``new_state``. Returns True if the transition happened.

        Illegal transitions are logged and rejected rather than raising, so
        a stray async callback can never crash the pipeline - it just loses
        the race, which is the correct behavior.
        """
        with self._lock:
            old_state = self._state
            if not force and new_state not in _ALLOWED_TRANSITIONS.get(old_state, set()):
                logger.debug(
                    "Rejected illegal state transition %s -> %s", old_state, new_state
                )
                return False
            self._state = new_state
            self._last_transition_ts = time.monotonic()
            listeners = list(self._listeners)

        logger.debug("State transition: %s -> %s", old_state, new_state)
        for listener in listeners:
            try:
                listener(old_state, new_state)
            except Exception:
                logger.exception("State listener raised an exception")
        return True

    def force_idle(self) -> None:
        """Panic-button reset used by error handlers - always succeeds."""
        self.transition(AppState.IDLE, force=True)

    def add_listener(self, listener: StateListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: StateListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def seconds_in_current_state(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_transition_ts
