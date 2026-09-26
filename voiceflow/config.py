"""Thread-safe, self-healing JSON configuration for VoiceFlow.

Design goals:
  * Zero-config first run - ``ConfigManager()`` creates a sane default file.
  * Forward-compatible - new keys added in later versions are deep-merged
    into an existing user config instead of clobbering it.
  * Dot-path access (``config.get("providers.groq_api_key")``) so callers
    never need to know the on-disk nesting to read/write a single value.
  * Every mutation is saved atomically (write to temp file, then rename) so
    a crash mid-write can never corrupt the config.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from voiceflow.paths import CONFIG_PATH, ensure_directories

logger = logging.getLogger("voiceflow.config")

DEFAULT_CONFIG: dict[str, Any] = {
    "version": 1,
    "providers": {
        # Which providers to try, in order, for each pipeline stage.
        # A provider is skipped automatically if it has no API key set.
        "transcription_order": ["groq", "openai", "local"],
        "formatting_order": ["groq", "openai", "anthropic"],
        "groq_api_key": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "groq_transcription_model": "whisper-large-v3-turbo",
        "groq_formatting_model": "llama-3.3-70b-versatile",
        "openai_transcription_model": "whisper-1",
        "openai_formatting_model": "gpt-4o-mini",
        "anthropic_formatting_model": "claude-haiku-4-5-20251001",
        "local_whisper_model_size": "base.en",
        "request_timeout_seconds": 20,
        "max_retries": 3,
    },
    "hotkey": {
        # See voiceflow/hotkeys/listener.py for the full key name list.
        "key": "alt_r",
        "hold_threshold_ms": 180,
        "double_tap_window_ms": 350,
        # "hybrid" (recommended): hold = hold-to-talk, double-tap = latch on/off
        # "hold": hold-to-talk only
        # "toggle": single tap starts, single tap stops
        "mode": "hybrid",
    },
    "audio": {
        "device": None,  # None = system default input device
        "sample_rate": 16000,
        "channels": 1,
        "max_recording_seconds": 120,
        "save_recordings_for_debug": False,
    },
    "formatting": {
        "remove_filler_words": True,
        "auto_punctuate": True,
        "learn_prefixes": ["learn:", "remember:"],
        "edit_prefixes": ["edit:", "rewrite:"],
        "preserve_tone": True,
    },
    "clipboard": {
        "restore_delay_ms": 250,
    },
    "memory": {
        "max_snippets_injected": 8,
        "max_entries": 2000,
    },
    "history": {
        "max_entries": 50,
    },
    "meeting": {
        "chunk_seconds": 20,
        "generate_summary": True,
        "min_chunk_seconds_to_transcribe": 1.5,
    },
    "ui": {
        "show_dock_icon": True,
        "launch_at_login": False,
        "sound_feedback": True,
        "menu_bar_icon_style": "waveform",
        "show_hud": True,
        "onboarding_shown": False,
    },
    "app_profiles_overrides": {},
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge ``overrides`` on top of ``base``, returning a new dict."""
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ConfigManager:
    """Loads, validates, and persists VoiceFlow's configuration."""

    def __init__(self, path: Path | None = None):
        self._path = path or CONFIG_PATH
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._listeners: list[Any] = []
        self._load_or_create()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load_or_create(self) -> None:
        ensure_directories()
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    on_disk = json.load(fh)
                self._data = _deep_merge(DEFAULT_CONFIG, on_disk)
                if self._data != on_disk:
                    # Schema evolved since this file was written - persist upgrade.
                    self._save_locked()
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Config file corrupt (%s); recreating from defaults", exc)
                backup = self._path.with_suffix(".json.bak")
                try:
                    self._path.replace(backup)
                    logger.info("Corrupt config backed up to %s", backup)
                except OSError:
                    pass
                self._data = copy.deepcopy(DEFAULT_CONFIG)
                self._save_locked()
        else:
            self._data = copy.deepcopy(DEFAULT_CONFIG)
            self._save_locked()

    def _save_locked(self) -> None:
        """Atomic write: write to a temp file in the same dir, then rename."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self._path.parent), prefix=".config_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
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
    # Dot-path access
    # ------------------------------------------------------------------ #
    def get(self, dotted_key: str, default: Any = None) -> Any:
        with self._lock:
            node: Any = self._data
            for part in dotted_key.split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    return default
            return copy.deepcopy(node)

    def set(self, dotted_key: str, value: Any, save: bool = True) -> None:
        with self._lock:
            parts = dotted_key.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            if save:
                self._save_locked()
            for callback in list(self._listeners):
                try:
                    callback(dotted_key, value)
                except Exception:
                    logger.exception("Config change listener raised")

    def update(self, values: dict[str, Any], save: bool = True) -> None:
        """Set multiple dotted keys atomically (one disk write)."""
        with self._lock:
            for key, value in values.items():
                self.set(key, value, save=False)
            if save:
                self._save_locked()

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._data)

    def on_change(self, callback) -> None:
        """Register a ``callback(key, value)`` invoked after every ``set``."""
        self._listeners.append(callback)

    # ------------------------------------------------------------------ #
    # Convenience helpers used throughout the app
    # ------------------------------------------------------------------ #
    def configured_providers(self, order_key: str) -> list[str]:
        """Return provider names from e.g. ``providers.transcription_order``
        filtered down to ones that actually have credentials configured
        (the "local" provider never needs a key)."""
        order = self.get(order_key, [])
        available = []
        for name in order:
            if name == "local":
                available.append(name)
                continue
            key = self.get(f"providers.{name}_api_key", "")
            if key:
                available.append(name)
        return available

    def has_any_provider_configured(self) -> bool:
        for name in ("groq", "openai", "anthropic"):
            if self.get(f"providers.{name}_api_key", ""):
                return True
        return False
