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
    # Deliberately NOT ~/Documents: macOS treats Documents/Desktop/Downloads
    # as TCC-protected folders requiring their own separate user consent
    # prompt, which VoiceFlow never requests/declares in Info.plist - an
    # app writing there without that permission gets a silent
    # PermissionError. Living under Application Support (which the app
    # already has unprompted access to, same as config/memory/logs) avoids
    # that failure mode entirely.
    return APP_SUPPORT_DIR / "Meeting Notes"


MEETING_NOTES_DIR = _default_meeting_notes_dir()


def ensure_directories() -> None:
    """Create every directory VoiceFlow needs. Safe to call repeatedly."""
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)


def ensure_meeting_notes_dir() -> None:
    MEETING_NOTES_DIR.mkdir(parents=True, exist_ok=True)


SOURCE_DIR_SENTINEL_NAME = "source_dir.txt"


def find_source_dir(app_support_dir: Path, home_dir: Path) -> Path | None:
    """Locate the git checkout ``update_macos_app.sh`` lives in.

    The running .app bundle has no inherent link back to wherever its
    source was cloned from - build_macos_app.sh writes that location down
    (in ``<app_support_dir>/source_dir.txt``) the moment it produces a
    working build, specifically so this doesn't have to guess. Falls back
    to the conventional ``~/VoiceFlow`` this project's docs have
    consistently pointed people to, for a build made before that file
    started being written.

    Pure path logic - no filesystem writes, so it's safe to call from
    anywhere and easy to unit test with a tmp_path standing in for both
    directories.
    """
    candidates: list[Path] = []
    sentinel = app_support_dir / SOURCE_DIR_SENTINEL_NAME
    if sentinel.exists():
        try:
            recorded = sentinel.read_text().strip()
        except OSError:
            recorded = ""
        if recorded:
            candidates.append(Path(recorded))
    candidates.append(home_dir / "VoiceFlow")

    for candidate in candidates:
        if (candidate / "update_macos_app.sh").is_file():
            return candidate
    return None
