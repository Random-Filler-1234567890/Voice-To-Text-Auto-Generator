"""Tiny, non-blocking audio feedback using macOS's built-in system sounds.

We shell out to ``afplay`` on the stock ``/System/Library/Sounds`` AIFFs
rather than bundling our own audio assets or driving ``NSSound`` from a
background thread (which has main-thread-affinity gotchas) - this is the
simplest thing that reliably works from any thread.
"""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger("voiceflow.ui.sounds")

_SOUNDS_DIR = "/System/Library/Sounds"
_SOUND_START = "Tink"
_SOUND_STOP = "Pop"
_SOUND_ERROR = "Basso"
_SOUND_LEARNED = "Glass"


def _play(name: str) -> None:
    path = f"{_SOUNDS_DIR}/{name}.aiff"
    try:
        subprocess.Popen(
            ["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        logger.debug("Could not play sound %s (afplay unavailable?)", name, exc_info=True)


def play_start() -> None:
    _play(_SOUND_START)


def play_stop() -> None:
    _play(_SOUND_STOP)


def play_error() -> None:
    _play(_SOUND_ERROR)


def play_learned() -> None:
    _play(_SOUND_LEARNED)
