"""Launch-at-login via a user LaunchAgent plist.

We deliberately avoid the newer ``SMAppService`` API (macOS 13+, requires
an extra pyobjc framework and only behaves correctly when running from a
properly-signed bundle) in favor of the classic, dependency-free
``~/Library/LaunchAgents`` plist approach, which has worked identically
since Mac OS X 10.4 and needs nothing beyond the stdlib.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("voiceflow.ui.launch_agent")

_LABEL = "com.voiceflow.app"
_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"

_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" \
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>{app_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def is_enabled() -> bool:
    return _PLIST_PATH.exists()


def enable(app_bundle_path: str) -> bool:
    try:
        _PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PLIST_PATH.write_text(_PLIST_TEMPLATE.format(label=_LABEL, app_path=app_bundle_path))
        return True
    except OSError:
        logger.exception("Failed to write LaunchAgent plist")
        return False


def disable() -> bool:
    try:
        if _PLIST_PATH.exists():
            _PLIST_PATH.unlink()
        return True
    except OSError:
        logger.exception("Failed to remove LaunchAgent plist")
        return False
