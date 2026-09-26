"""Central definitions for every filesystem path VoiceFlow touches.

Keeping this in one module means every other component (config, memory,
logging) agrees on where things live, and tests can monkeypatch
``APP_SUPPORT_DIR`` to redirect everything into a temp directory.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "VoiceFlow"


def _default_app_support_dir() -> Path:
    """Return the platform-appropriate application-support directory.

    On macOS this is ``~/Library/Application Support/VoiceFlow``. On any
    other platform (used only for running the test suite / linting in CI)
    we fall back to a dotfile in the home directory so the module can still
    be imported and exercised.
    """
    override = os.environ.get("VOICEFLOW_HOME")
    if override:
        return Path(override).expanduser()

    home = Path.home()
    mac_dir = home / "Library" / "Application Support" / APP_NAME
    if mac_dir.parent.exists() or os.uname().sysname == "Darwin":
        return mac_dir
    return home / f".{APP_NAME.lower()}"


APP_SUPPORT_DIR = _default_app_support_dir()
CONFIG_PATH = APP_SUPPORT_DIR / "config.json"
MEMORY_PATH = APP_SUPPORT_DIR / "memory.json"
HISTORY_PATH = APP_SUPPORT_DIR / "history.json"
STATS_PATH = APP_SUPPORT_DIR / "stats.json"
LOG_DIR = APP_SUPPORT_DIR / "logs"
LOG_PATH = LOG_DIR / "voiceflow.log"
RECORDINGS_DIR = APP_SUPPORT_DIR / "recordings"  # only used if debug save is enabled


def _default_meeting_notes_dir() -> Path:
    override = os.environ.get("VOICEFLOW_MEETING_NOTES_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Documents" / "VoiceFlow Notes"


MEETING_NOTES_DIR = _default_meeting_notes_dir()


def ensure_directories() -> None:
    """Create every directory VoiceFlow needs. Safe to call repeatedly."""
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_meeting_notes_dir() -> None:
    MEETING_NOTES_DIR.mkdir(parents=True, exist_ok=True)
