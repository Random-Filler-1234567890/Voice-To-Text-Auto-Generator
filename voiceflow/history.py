"""Rolling history of recent dictations, so you can recall/recopy one you
just said without having to say it again if the paste went to the wrong
place or you closed the window too fast to read it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from voiceflow.paths import HISTORY_PATH, ensure_directories


@dataclass
class HistoryEntry:
    text: str
    app_name: str
    word_count: int
    created_at: float

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "HistoryEntry":
        return HistoryEntry(
            text=data["text"],
            app_name=data.get("app_name", ""),
            word_count=data.get("word_count", 0),
            created_at=data.get("created_at", time.time()),
        )


class DictationHistory:
    """Thread-safe, capped, JSON-persisted list of recent dictations (newest first)."""

    def __init__(self, path: Path | None = None, max_entries: int = 50):
        self._path = path or HISTORY_PATH
        self._max_entries = max_entries
        self._lock = threading.RLock()
        self._entries: list[HistoryEntry] = []
        self._load_or_create()

    def _load_or_create(self) -> None:
        ensure_directories()
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                self._entries = [HistoryEntry.from_dict(d) for d in raw.get("entries", [])]
                return
            except (json.JSONDecodeError, OSError, KeyError):
                try:
                    self._path.replace(self._path.with_suffix(".json.bak"))
                except OSError:
                    pass
        self._entries = []
        self._save_locked()

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [e.to_dict() for e in self._entries]}
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), prefix=".history_", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def record(self, text: str, app_name: str = "") -> HistoryEntry:
        text = text.strip()
        entry = HistoryEntry(
            text=text,
            app_name=app_name,
            word_count=len(text.split()),
            created_at=time.time(),
        )
        with self._lock:
            self._entries.insert(0, entry)
            del self._entries[self._max_entries :]
            self._save_locked()
        return entry

    def recent(self, limit: int = 10) -> list[HistoryEntry]:
        with self._lock:
            return list(self._entries[:limit])

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._save_locked()

    def count(self) -> int:
        with self._lock:
            return len(self._entries)
