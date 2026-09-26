"""A small floating "listening" indicator - VoiceFlow's answer to Wispr
Flow's floating orb. Appears near the bottom of the screen while recording
or processing, and disappears the moment you're back to idle.

This is the single riskiest piece of UI code in the app: real, hand-written
AppKit window creation that could not be exercised on a real display before
reaching you. Every public method is defensive - if window creation ever
fails for any reason (unexpected macOS version, missing framework, etc.)
it logs once and permanently disables itself rather than raising, so a HUD
bug can never take down actual dictation. It's also fully toggleable from
the menu ("Show Listening Indicator") if it ever misbehaves.

All AppKit calls are marshaled onto the main thread via
``PyObjCTools.AppHelper.callAfter`` since state changes that trigger
show()/hide() arrive from background threads (the pipeline's worker
thread, the hotkey listener thread) and AppKit window operations are only
safe to perform on the main thread.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("voiceflow.ui.hud")

try:
    from AppKit import (
        NSBackingStoreBuffered,
        NSColor,
        NSFloatingWindowLevel,
        NSFont,
        NSTextAlignmentCenter,
        NSTextField,
        NSScreen,
        NSView,
        NSWindow,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorStationary,
        NSWindowStyleMaskBorderless,
    )
    from PyObjCTools import AppHelper

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only off-macOS
    _APPKIT_AVAILABLE = False

_WIDTH = 240
_HEIGHT = 52
_BOTTOM_MARGIN_FRACTION = 0.12


class ListeningHUD:
    def __init__(self) -> None:
        self._enabled = _APPKIT_AVAILABLE
        self._window = None
        self._label = None
        if not self._enabled:
            logger.info("AppKit unavailable - listening HUD will stay disabled")

    # ------------------------------------------------------------------ #
    # Public API - safe to call from any thread
    # ------------------------------------------------------------------ #
    def show(self, text: str) -> None:
        if not self._enabled:
            return
        AppHelper.callAfter(self._do_show, text)

    def hide(self) -> None:
        if not self._enabled:
            return
        AppHelper.callAfter(self._do_hide)

    def update_text(self, text: str) -> None:
        if not self._enabled:
            return
        AppHelper.callAfter(self._do_update_text, text)

    # ------------------------------------------------------------------ #
    # Main-thread-only implementation
    # ------------------------------------------------------------------ #
    def _ensure_window(self) -> bool:
        if self._window is not None:
            return True
        try:
            screen_frame = NSScreen.mainScreen().frame()
            x = (screen_frame.size.width - _WIDTH) / 2.0
            y = screen_frame.size.height * _BOTTOM_MARGIN_FRACTION
            rect = ((x, y), (_WIDTH, _HEIGHT))

            window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False
            )
            window.setLevel_(NSFloatingWindowLevel)
            window.setOpaque_(False)
            window.setBackgroundColor_(NSColor.clearColor())
            window.setHasShadow_(True)
            window.setIgnoresMouseEvents_(True)
            window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
            )

            content = NSView.alloc().initWithFrame_(((0, 0), (_WIDTH, _HEIGHT)))
            content.setWantsLayer_(True)
            layer = content.layer()
            layer.setBackgroundColor_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.10, 0.12, 0.90).CGColor()
            )
            layer.setCornerRadius_(_HEIGHT / 2.0)

            label = NSTextField.alloc().initWithFrame_(((10, 0), (_WIDTH - 20, _HEIGHT)))
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setBordered_(False)
            label.setDrawsBackground_(False)
            label.setAlignment_(NSTextAlignmentCenter)
            label.setTextColor_(NSColor.whiteColor())
            try:
                label.setFont_(NSFont.systemFontOfSize_(14))
            except Exception:
                pass
            content.addSubview_(label)

            window.setContentView_(content)

            self._window = window
            self._label = label
            return True
        except Exception:
            logger.exception("Failed to create the listening HUD window; disabling it")
            self._enabled = False
            self._window = None
            self._label = None
            return False

    def _do_show(self, text: str) -> None:
        if not self._ensure_window():
            return
        try:
            self._label.setStringValue_(text)
            self._window.orderFront_(None)
        except Exception:
            logger.exception("Failed to show the listening HUD")

    def _do_hide(self) -> None:
        if self._window is None:
            return
        try:
            self._window.orderOut_(None)
        except Exception:
            logger.exception("Failed to hide the listening HUD")

    def _do_update_text(self, text: str) -> None:
        if self._window is None or self._label is None:
            return
        try:
            self._label.setStringValue_(text)
        except Exception:
            logger.exception("Failed to update the listening HUD text")
