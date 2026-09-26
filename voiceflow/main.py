"""VoiceFlow entry point.

Dev mode:      python -m voiceflow.main
Packaged app:  built by py2app (see build_macos_app.sh); the .app bundle's
               executable calls this same ``run()`` function.
"""

from __future__ import annotations

import sys


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

    from voiceflow.app import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
