"""VoiceFlow entry point.

Dev mode:      python -m voiceflow.main
Packaged app:  built by py2app (see build_macos_app.sh); the .app bundle's
               executable calls this same ``main()`` function.

This module is deliberately paranoid: it is the one place in the whole
codebase where an unhandled failure must NEVER be allowed to fail
*silently*. A double-clicked .app has no attached terminal - if something
raises before the menu bar icon appears, the user just sees nothing
happen at all, with zero way to tell us what went wrong. Every code path
below guarantees two things on failure: (1) a full traceback is written to
a plain text file whose path never depends on any of VoiceFlow's own
modules having imported successfully, and (2) a native macOS alert pops up
telling the user exactly where that file is - using only ``osascript``
(no PyObjC/rumps dependency at all), so this works even if the
AppKit/PyObjC stack itself is what's broken.
"""

from __future__ import annotations

import datetime
import subprocess
import sys
import traceback
from pathlib import Path

_CRASH_LOG_PATH = Path.home() / "Library" / "Application Support" / "VoiceFlow" / "logs" / "crash.log"


def _write_crash_log(context: str, exc: BaseException) -> Path:
    try:
        _CRASH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CRASH_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(f"\n{'=' * 70}\n")
            fh.write(f"{datetime.datetime.now().isoformat()} - VoiceFlow failed to start\n")
            fh.write(f"Stage: {context}\n")
            fh.write(f"Python: {sys.version}\n")
            fh.write(f"Executable: {sys.executable}\n\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        # If we can't even write the crash log, fall back to stderr - at
        # least something has a chance of surviving if run from a terminal.
        traceback.print_exc()
    return _CRASH_LOG_PATH


def _applescript_escape(text: str) -> str:
    """Escape a string for safe interpolation into a double-quoted AppleScript literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _show_native_alert(title: str, message: str) -> None:
    """Show a macOS alert with zero dependency on PyObjC/rumps working.

    Uses ``osascript`` (AppleScript), which is a stock macOS binary present
    on every Mac regardless of whether anything Python-side is broken.
    """
    safe_title = _applescript_escape(title)
    safe_message = _applescript_escape(message)
    script = f'display alert "{safe_title}" message "{safe_message}" as critical'
    try:
        subprocess.run(["osascript", "-e", script], timeout=15, check=False)
    except Exception:
        pass  # If even this fails, the crash log on disk is the last resort.


def main() -> int:
    if sys.platform != "darwin":
        print(
            "VoiceFlow's menu bar app only runs on macOS. "
            "(The core pipeline modules are cross-platform and covered by "
            "the test suite - see tests/ - but audio capture, global "
            "hotkeys, clipboard injection, and the menu bar UI are "
            "macOS-only.)",
            file=sys.stderr,
        )
        return 1

    try:
        from voiceflow.app import run
    except BaseException as exc:  # noqa: BLE001 - see module docstring
        log_path = _write_crash_log("importing voiceflow.app", exc)
        _show_native_alert(
            "VoiceFlow failed to start",
            f"An error occurred while loading VoiceFlow: {exc}. "
            f"Details were saved to {log_path}. Run './run_dev.sh' in Terminal "
            f"from the VoiceFlow source folder to see the full error.",
        )
        return 1

    try:
        run()
    except BaseException as exc:  # noqa: BLE001 - see module docstring
        log_path = _write_crash_log("running VoiceFlow", exc)
        _show_native_alert(
            "VoiceFlow crashed",
            f"An error occurred: {exc}. Details were saved to {log_path}. "
            f"Run './run_dev.sh' in Terminal from the VoiceFlow source folder "
            f"to see the full error.",
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
