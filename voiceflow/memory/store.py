"""Persistent, JSON-backed personal memory profile.

This is the "crown jewel" long-term memory: facts, vocabulary, people, and
spelling/acronym corrections the user has explicitly taught VoiceFlow (via
the "Learn:" / "Remember:" dictation prefix), plus corrections it infers
automatically. Every normal dictation queries this store for relevant
snippets (via :class:`~voiceflow.memory.relevance.RelevanceRanker`) which
get folded into the LLM system prompt as custom vocabulary/context.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from voiceflow.memory.relevance import RelevanceRanker
from voiceflow.paths import MEMORY_PATH, ensure_directories

logger = logging.getLogger("voiceflow.memory")

VALID_CATEGORIES = {"fact", "person", "vocabulary", "acronym", "correction", "preference"}


@dataclass
class MemoryEntry:
    id: str
    category: str
    text: str
    created_at: float
    source: str = "learn_command"
    use_count: int = 0
    last_used_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "MemoryEntry":
        return MemoryEntry(
            id=data["id"],
            category=data.get("category", "fact"),
            text=data["text"],
            created_at=data.get("created_at", time.time()),
            source=data.get("source", "learn_command"),
            use_count=data.get("use_count", 0),
            last_used_at=data.get("last_used_at"),
        )


class MemoryStore:
    """Thread-safe CRUD + relevance search over the personal memory profile."""

    def __init__(self, path: Path | None = None, max_entries: int = 2000):
        self._path = path or MEMORY_PATH
        self._max_entries = max_entries
        self._lock = threading.RLock()
        self._entries: dict[str, MemoryEntry] = {}
        self._ranker = RelevanceRanker()
        self._load_or_create()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load_or_create(self) -> None:
        ensure_directories()
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                for entry_dict in raw.get("entries", []):
                    entry = MemoryEntry.from_dict(entry_dict)
                    self._entries[entry.id] = entry
                return
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.error("Memory file corrupt (%s); backing up and starting fresh", exc)
                try:
                    self._path.replace(self._path.with_suffix(".json.bak"))
                except OSError:
                    pass
        self._entries = {}
        self._save_locked()

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"entries": [e.to_dict() for e in self._entries.values()]}
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), prefix=".memory_", suffix=".tmp")
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

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #
    def add_entry(
        self, category: str, text: str, source: str = "learn_command"
    ) -> MemoryEntry:
        text = text.strip()
        if not text:
            raise ValueError("Cannot add an empty memory entry")
        if category not in VALID_CATEGORIES:
            logger.warning("Unknown memory category %r, defaulting to 'fact'", category)
            category = "fact"

        with self._lock:
            entry = MemoryEntry(
                id=str(uuid.uuid4()),
                category=category,
                text=text,
                created_at=time.time(),
                source=source,
            )
            self._entries[entry.id] = entry
            self._enforce_capacity_locked()
            self._save_locked()
            logger.info("Memory learned [%s]: %s", category, text)
            return entry

    def learn_from_facts(self, facts: list[dict]) -> list[MemoryEntry]:
        """Bulk-add facts extracted by the LLM from a 'Learn:' dictation.

        Each fact dict looks like ``{"category": "person", "text": "..."}``.
        Malformed entries are skipped rather than raising, so one bad item
        from an LLM response doesn't discard the rest of a good extraction.
        """
        added = []
        with self._lock:
            for fact in facts:
                try:
                    text = str(fact["text"]).strip()
                    category = str(fact.get("category", "fact")).strip().lower()
                    if not text:
                        continue
                    if category not in VALID_CATEGORIES:
                        category = "fact"
                    entry = MemoryEntry(
                        id=str(uuid.uuid4()),
                        category=category,
                        text=text,
                        created_at=time.time(),
                        source="learn_command",
                    )
                    self._entries[entry.id] = entry
                    added.append(entry)
                except (KeyError, TypeError, ValueError):
                    logger.warning("Skipping malformed extracted fact: %r", fact)
            if added:
                self._enforce_capacity_locked()
                self._save_locked()
        return added

    def delete_entry(self, entry_id: str) -> bool:
        with self._lock:
            if entry_id in self._entries:
                del self._entries[entry_id]
                self._save_locked()
                return True
            return False

    def update_entry(self, entry_id: str, text: str) -> bool:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                return False
            entry.text = text.strip()
            self._save_locked()
            return True

    def _enforce_capacity_locked(self) -> None:
        """Evict the least-recently-used entries beyond ``max_entries``."""
        if len(self._entries) <= self._max_entries:
            return
        ranked = sorted(
            self._entries.values(),
            key=lambda e: (e.last_used_at or e.created_at),
        )
        overflow = len(self._entries) - self._max_entries
        for entry in ranked[:overflow]:
            logger.info("Evicting least-used memory entry: %s", entry.text[:60])
            del self._entries[entry.id]

    # ------------------------------------------------------------------ #
    # Read access
    # ------------------------------------------------------------------ #
    def all_entries(self) -> list[MemoryEntry]:
        with self._lock:
            return sorted(
                (copy.deepcopy(e) for e in self._entries.values()),
                key=lambda e: e.created_at,
                reverse=True,
            )

    def entries_by_category(self, category: str) -> list[MemoryEntry]:
        with self._lock:
            return [copy.deepcopy(e) for e in self._entries.values() if e.category == category]

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def relevant_snippets(self, query_text: str, max_results: int = 8) -> list[str]:
        """Return the ``max_results`` memory snippets most relevant to a dictation.

        Marks matched entries' ``use_count``/``last_used_at`` so frequently
        useful facts get a small recency edge over time (a lightweight form
        of "the app learns what matters to you").
        """
        with self._lock:
            if not self._entries:
                return []
            corpus = [(e.id, e.text) for e in self._entries.values()]
            timestamps = {
                e.id: (e.last_used_at or e.created_at) for e in self._entries.values()
            }
            scored = self._ranker.rank(
                query_text, corpus, timestamps=timestamps, top_k=max_results
            )
            snippets = []
            now = time.time()
            for item in scored:
                entry = self._entries[item.item_id]
                entry.use_count += 1
                entry.last_used_at = now
                snippets.append(entry.text)
            if scored:
                self._save_locked()
            return snippets
