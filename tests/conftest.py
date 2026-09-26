import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class FakeCancelHandle:
    def __init__(self, entry):
        self._entry = entry

    def cancel(self):
        self._entry["cancelled"] = True


class FakeScheduler:
    """Deterministic stand-in for ThreadingScheduler.

    Captures every scheduled callback instead of using real timers/threads,
    so tests can advance "time" by explicitly firing due callbacks in a
    controlled order - no sleeps, no flakiness.
    """

    def __init__(self):
        self.scheduled: list[dict] = []

    def schedule(self, delay_ms, callback):
        entry = {"delay_ms": delay_ms, "callback": callback, "cancelled": False}
        self.scheduled.append(entry)
        return FakeCancelHandle(entry)

    def fire_next(self):
        """Fire the oldest non-cancelled, not-yet-fired callback."""
        for entry in self.scheduled:
            if not entry["cancelled"] and not entry.get("fired"):
                entry["fired"] = True
                entry["callback"]()
                return
        raise AssertionError("No pending scheduled callback to fire")

    def fire_all_pending(self):
        for entry in list(self.scheduled):
            if not entry["cancelled"] and not entry.get("fired"):
                entry["fired"] = True
                entry["callback"]()

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self.scheduled if not e["cancelled"] and not e.get("fired"))


@pytest.fixture
def fake_scheduler():
    return FakeScheduler()


@pytest.fixture
def tmp_config_path(tmp_path):
    return tmp_path / "config.json"


@pytest.fixture
def tmp_memory_path(tmp_path):
    return tmp_path / "memory.json"
