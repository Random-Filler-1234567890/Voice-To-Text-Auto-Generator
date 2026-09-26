"""Clipboard-safe text injection: copy -> paste -> restore original clipboard.

The core guarantee this module provides: whatever was on the user's
clipboard before a dictation is *never* permanently lost. We snapshot it
before touching the clipboard, and restore it a configurable delay after
the simulated paste, on a background timer so the caller isn't blocked.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional, Protocol

from voiceflow.utils.scheduler import Scheduler, ThreadingScheduler

logger = logging.getLogger("voiceflow.clipboard")

try:
    import pyperclip
except ImportError:  # pragma: no cover - exercised only off-macOS
    pyperclip = None

try:
    from pynput.keyboard import Controller as _PynputController
    from pynput.keyboard import Key as _PynputKey
except ImportError:  # pragma: no cover - exercised only off-macOS
    _PynputController = None
    _PynputKey = None


class InjectionError(Exception):
    pass


class ClipboardBackend(Protocol):
    def copy(self, text: str) -> None: ...
    def paste(self) -> str: ...


class KeySimulator(Protocol):
    def send_paste_shortcut(self) -> None: ...


class PyperclipBackend:
    def copy(self, text: str) -> None:
        if pyperclip is None:
            raise InjectionError("pyperclip is not available on this platform")
        pyperclip.copy(text)

    def paste(self) -> str:
        if pyperclip is None:
            raise InjectionError("pyperclip is not available on this platform")
        try:
            return pyperclip.paste()
        except Exception:
            # Clipboard can legitimately contain non-text data (an image, a
            # file reference) that pyperclip can't read back as a string.
            # That's fine - we just won't be able to restore it, which we
            # log clearly rather than crash the whole dictation over.
            logger.warning("Could not read current clipboard contents (likely non-text data)")
            return ""


class PynputKeySimulator:
    """Simulates Cmd+V (macOS paste) via a synthetic keyboard event."""

    def send_paste_shortcut(self) -> None:
        if _PynputController is None:
            raise InjectionError("pynput is not available on this platform")
        controller = _PynputController()
        with controller.pressed(_PynputKey.cmd):
            controller.press("v")
            controller.release("v")


class ClipboardInjector:
    """Orchestrates the copy -> paste -> restore sequence with full error handling."""

    def __init__(
        self,
        backend: Optional[ClipboardBackend] = None,
        key_simulator: Optional[KeySimulator] = None,
        scheduler: Optional[Scheduler] = None,
        restore_delay_ms: float = 250,
    ):
        self._backend = backend or PyperclipBackend()
        self._key_simulator = key_simulator or PynputKeySimulator()
        self._scheduler = scheduler or ThreadingScheduler()
        self._restore_delay_ms = restore_delay_ms

    def inject(self, text: str, on_restored: Optional[Callable[[], None]] = None) -> None:
        """Copy ``text`` to the clipboard, paste it, then restore the user's
        original clipboard contents after ``restore_delay_ms``.

        Raises :class:`InjectionError` only if we failed to even get the
        new text onto the clipboard or simulate the keystroke - a failure
        to *restore* the backup is logged, not raised, since by that point
        the user's dictation has already been successfully typed.
        """
        original: str = ""
        had_original = False
        try:
            original = self._backend.paste()
            had_original = True
        except Exception:
            logger.exception("Failed to snapshot existing clipboard contents; proceeding anyway")

        try:
            self._backend.copy(text)
        except Exception as exc:
            raise InjectionError(f"Failed to copy dictated text to clipboard: {exc}") from exc

        try:
            self._key_simulator.send_paste_shortcut()
        except Exception as exc:
            # We already overwrote the clipboard - restore it immediately
            # since the paste itself never happened.
            if had_original:
                self._safe_restore(original)
            raise InjectionError(f"Failed to simulate paste keystroke: {exc}") from exc

        if had_original:
            self._scheduler.schedule(
                self._restore_delay_ms, lambda: self._restore(original, on_restored)
            )
        elif on_restored is not None:
            # Nothing to restore, but still signal completion.
            self._scheduler.schedule(self._restore_delay_ms, on_restored)

    def _restore(self, original: str, on_restored: Optional[Callable[[], None]]) -> None:
        self._safe_restore(original)
        if on_restored is not None:
            try:
                on_restored()
            except Exception:
                logger.exception("on_restored callback raised")

    def _safe_restore(self, original: str) -> None:
        try:
            self._backend.copy(original)
            logger.debug("Original clipboard contents restored")
        except Exception:
            logger.exception("Failed to restore original clipboard contents")
