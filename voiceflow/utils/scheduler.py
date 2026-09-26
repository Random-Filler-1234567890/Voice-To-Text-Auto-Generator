"""Shared "run this after N milliseconds" abstraction.

Used by both the hotkey state machine (hold/double-tap timing windows) and
the clipboard injector (delayed clipboard restore). Abstracting it lets
unit tests substitute a fake scheduler and assert on exact timing logic
without any real sleeping - see ``tests/conftest.py::FakeScheduler``.
"""

from __future__ import annotations

import threading
from typing import Callable, Protocol


class CancelHandle(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    def schedule(self, delay_ms: float, callback: Callable[[], None]) -> CancelHandle: ...


class ThreadingScheduler:
    """Real-time scheduler backed by ``threading.Timer``."""

    class _Handle:
        def __init__(self, timer: threading.Timer):
            self._timer = timer

        def cancel(self) -> None:
            self._timer.cancel()

    def schedule(self, delay_ms: float, callback: Callable[[], None]) -> "ThreadingScheduler._Handle":
        timer = threading.Timer(delay_ms / 1000.0, callback)
        timer.daemon = True
        timer.start()
        return ThreadingScheduler._Handle(timer)
