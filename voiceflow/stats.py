"""Lightweight usage stats: words dictated, dictation count, estimated time saved.

Time-saved is a standard heuristic (the same one Wispr Flow and similar
dictation tools surface): the difference between how long it would have
taken to type the same words versus how long it takes to speak them, using
typical average speeds. It's an estimate, not a measurement of your actual
elapsed time - it deliberately doesn't try to be more precise than that.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from voiceflow.paths import STATS_PATH, ensure_directories

AVERAGE_TYPING_WPM = 40
AVERAGE_SPEAKING_WPM = 150


@dataclass
class _StatsData:
    total_dictations: int = 0
    total_words: int = 0
    total_facts_learned: int = 0
    total_meetings: int = 0
    total_meeting_words: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class UsageStats:
    """Thread-safe, JSON-persisted usage counters."""

    def __init__(self, path: Path | None = None):
        self._path = path or STATS_PATH
        self._lock = threading.RLock()
        self._data = _StatsData()
        self._load_or_create()

    def _load_or_create(self) -> None:
        ensure_directories()
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                self._data = _StatsData(
                    total_dictations=raw.get("total_dictations", 0),
                    total_words=raw.get("total_words", 0),
                    total_facts_learned=raw.get("total_facts_learned", 0),
                    total_meetings=raw.get("total_meetings", 0),
                    total_meeting_words=raw.get("total_meeting_words", 0),
                )
                return
            except (json.JSONDecodeError, OSError, KeyError):
                try:
                    self._path.replace(self._path.with_suffix(".json.bak"))
                except OSError:
                    pass
        self._data = _StatsData()
        self._save_locked()

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), prefix=".stats_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data.to_dict(), fh, indent=2)
                fh.write("\n")
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def record_dictation(self, word_count: int) -> None:
        with self._lock:
            self._data.total_dictations += 1
            self._data.total_words += max(0, word_count)
            self._save_locked()

    def record_fact_learned(self) -> None:
        with self._lock:
            self._data.total_facts_learned += 1
            self._save_locked()

    def record_meeting(self, word_count: int) -> None:
        with self._lock:
            self._data.total_meetings += 1
            self._data.total_meeting_words += max(0, word_count)
            self._save_locked()

    @property
    def total_dictations(self) -> int:
        with self._lock:
            return self._data.total_dictations

    @property
    def total_words(self) -> int:
        with self._lock:
            return self._data.total_words + self._data.total_meeting_words

    @property
    def total_facts_learned(self) -> int:
        with self._lock:
            return self._data.total_facts_learned

    @property
    def estimated_minutes_saved(self) -> float:
        with self._lock:
            words = self._data.total_words + self._data.total_meeting_words
        typing_minutes = words / AVERAGE_TYPING_WPM
        speaking_minutes = words / AVERAGE_SPEAKING_WPM
        return max(0.0, typing_minutes - speaking_minutes)

    def summary_line(self) -> str:
        words = self.total_words
        minutes = self.estimated_minutes_saved
        if words == 0:
            return "No dictations yet"
        if minutes < 1:
            return f"{words:,} words dictated"
        return f"{words:,} words dictated - ~{minutes:.0f} min saved"
