"""VoiceFlow's main status/settings window - a real, persistent interface
as an alternative to hunting through the status-bar dropdown and reading
transient notifications.

This is, by a wide margin, the largest piece of hand-written,
never-executed-on-real-macOS AppKit code in the app: a titled NSWindow
with buttons and text fields wired up via manual PyObjC target-action
plumbing. It is written as conservatively as possible - only the most
standard, widely-documented Cocoa patterns, fixed frame-based layout
(no Auto Layout constraints), no custom drawing, no exotic window
levels - specifically because that combination of choices is the most
likely to actually work first try on a real Mac.

It is entirely additive: every control here duplicates something already
reachable from the status-bar menu. If this window fails to build for any
reason, the app logs it and carries on with the menu as the sole
interface, exactly as it always has.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger("voiceflow.ui.main_window")

try:
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSButton,
        NSFont,
        NSObject,
        NSTextField,
        NSView,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskTitled,
    )
    from PyObjCTools import AppHelper

    try:
        from ApplicationServices import AXIsProcessTrusted
    except ImportError:
        AXIsProcessTrusted = None

    _APPKIT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only off-macOS
    _APPKIT_AVAILABLE = False

_WINDOW_WIDTH = 380
_WINDOW_HEIGHT = 542
_MARGIN = 20
_ROW_HEIGHT = 26
_ROW_GAP = 10


if _APPKIT_AVAILABLE:

    class _ActionTarget(NSObject):
        """A tiny NSObject that forwards a button click to a Python callable.

        AppKit's setTarget_/setAction_ need an Objective-C-message-capable
        target - a plain Python function can't be one - so every
        interactive control gets one of these, each wrapping one callback.
        The caller MUST keep a strong reference to every instance created
        (stored in MainWindowController._targets below): AppKit's
        setTarget_ does not retain its target, so a Python-side reference
        is the only thing keeping these alive between clicks.
        """

        def initWithCallback_(self, callback):
            self = objc.super(_ActionTarget, self).init()
            if self is None:
                return None
            self._callback = callback
            return self

        def invoke_(self, _sender):
            try:
                self._callback()
            except Exception:
                logger.exception("Main window button callback raised")


class MainWindowController:
    """Builds and manages VoiceFlow's main window.

    All AppKit object creation happens lazily, on the main thread (via
    AppHelper.callAfter), the first time :meth:`show` is called - never at
    construction time, so simply instantiating this class can never itself
    fail or touch AppKit.
    """

    def __init__(
        self,
        get_state_text: Callable[[], str],
        get_permission_statuses: Callable[[], dict],
        get_stats_text: Callable[[], str],
        get_dictation_button_text: Callable[[], str],
        get_meeting_button_text: Callable[[], str],
        on_toggle_dictation: Callable[[], None],
        on_toggle_meeting: Callable[[], None],
        on_test_microphone: Callable[[], None],
        on_open_settings_pane: Callable[[str], None],
        on_save_groq_key: Callable[[str], None],
        on_update_app: Callable[[], None],
    ) -> None:
        self._enabled = _APPKIT_AVAILABLE
        self._get_state_text = get_state_text
        self._get_permission_statuses = get_permission_statuses
        self._get_stats_text = get_stats_text
        self._get_dictation_button_text = get_dictation_button_text
        self._get_meeting_button_text = get_meeting_button_text
        self._on_toggle_dictation = on_toggle_dictation
        self._on_toggle_meeting = on_toggle_meeting
        self._on_test_microphone = on_test_microphone
        self._on_open_settings_pane = on_open_settings_pane
        self._on_save_groq_key = on_save_groq_key
        self._on_update_app = on_update_app

        self._window = None
        self._targets: list = []  # keeps _ActionTarget instances alive
        self._labels: dict = {}
        self._key_field = None

        if not self._enabled:
            logger.info("AppKit unavailable - the main window will stay disabled")

    # ------------------------------------------------------------------ #
    # Public API - safe to call from any thread
    # ------------------------------------------------------------------ #
    def show(self) -> None:
        if not self._enabled:
            return
        AppHelper.callAfter(self._do_show)

    def refresh(self) -> None:
        if not self._enabled or self._window is None:
            return
        AppHelper.callAfter(self._do_refresh)

    # ------------------------------------------------------------------ #
    # Main-thread-only implementation
    # ------------------------------------------------------------------ #
    def _do_show(self) -> None:
        try:
            if self._window is None:
                self._build_window()
            self._do_refresh()
            self._window.center()
            self._window.makeKeyAndOrderFront_(None)
            try:
                from AppKit import NSApp

                NSApp.activateIgnoringOtherApps_(True)
            except Exception:
                pass
        except Exception:
            logger.exception("Failed to show the main window; disabling it")
            self._enabled = False
            self._window = None

    def _build_window(self) -> None:
        style = (
            NSWindowStyleMaskTitled
            | NSWindowStyleMaskClosable
            | NSWindowStyleMaskMiniaturizable
        )
        rect = ((0, 0), (_WINDOW_WIDTH, _WINDOW_HEIGHT))
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style, NSBackingStoreBuffered, False
        )
        window.setTitle_("VoiceFlow")
        # Closing the window (red button) just hides it - alloc'ing a fresh
        # NSWindow every time this is reopened is unnecessary and riskier.
        window.setReleasedWhenClosed_(False)

        content = NSView.alloc().initWithFrame_(((0, 0), (_WINDOW_WIDTH, _WINDOW_HEIGHT)))
        y = _WINDOW_HEIGHT - _MARGIN - _ROW_HEIGHT

        self._add_label(content, "VoiceFlow", y, bold=True, size=18)
        y -= _ROW_HEIGHT
        self._labels["state"] = self._add_label(content, "...", y)
        y -= _ROW_HEIGHT + _ROW_GAP

        y = self._add_section_label(content, "Permissions", y)
        self._labels["mic_status"] = self._add_label(content, "...", y, x=_MARGIN, width=200)
        self._add_button(content, "Test Mic", y - 2, self._on_test_microphone, x=240, width=120, height=22)
        y -= _ROW_HEIGHT

        self._labels["accessibility_status"] = self._add_label(content, "...", y, x=_MARGIN, width=200)
        self._add_button(
            content,
            "Open Settings",
            y - 2,
            lambda: self._on_open_settings_pane("accessibility"),
            x=240,
            width=120,
            height=22,
        )
        y -= _ROW_HEIGHT

        self._add_label(content, "Input Monitoring (for hotkey)", y, x=_MARGIN, width=200)
        self._add_button(
            content,
            "Open Settings",
            y - 2,
            lambda: self._on_open_settings_pane("input_monitoring"),
            x=240,
            width=120,
            height=22,
        )
        y -= _ROW_HEIGHT + _ROW_GAP

        y = self._add_section_label(content, "Quick Actions", y)
        self._labels["dictation_button"] = self._add_button(
            content, "Start Dictation", y, self._on_toggle_dictation, x=_MARGIN, width=_WINDOW_WIDTH - 2 * _MARGIN
        )
        y -= _ROW_HEIGHT
        self._labels["meeting_button"] = self._add_button(
            content,
            "Start Meeting Notes",
            y,
            self._on_toggle_meeting,
            x=_MARGIN,
            width=_WINDOW_WIDTH - 2 * _MARGIN,
        )
        y -= _ROW_HEIGHT + _ROW_GAP

        y = self._add_section_label(content, "AI Provider (Groq)", y)
        self._key_field = NSTextField.alloc().initWithFrame_(
            ((_MARGIN, y), (_WINDOW_WIDTH - 2 * _MARGIN - 90, _ROW_HEIGHT))
        )
        self._key_field.setPlaceholderString_("Paste your Groq API key")
        content.addSubview_(self._key_field)
        self._add_button(
            content, "Save", y, self._handle_save_key, x=_WINDOW_WIDTH - _MARGIN - 80, width=80
        )
        y -= _ROW_HEIGHT
        self._labels["key_status"] = self._add_label(content, "", y, x=_MARGIN, width=_WINDOW_WIDTH - 2 * _MARGIN)
        y -= _ROW_HEIGHT + _ROW_GAP

        y = self._add_section_label(content, "Usage", y)
        self._labels["stats"] = self._add_label(content, "...", y, x=_MARGIN, width=_WINDOW_WIDTH - 2 * _MARGIN)
        y -= _ROW_HEIGHT + _ROW_GAP

        y = self._add_section_label(content, "Maintenance", y)
        self._add_button(
            content,
            "Update VoiceFlow...",
            y,
            self._on_update_app,
            x=_MARGIN,
            width=_WINDOW_WIDTH - 2 * _MARGIN,
        )
        y -= _ROW_HEIGHT + _ROW_GAP

        self._add_label(
            content,
            "For hotkey, memory, and more, use the menu bar icon.",
            y,
            x=_MARGIN,
            width=_WINDOW_WIDTH - 2 * _MARGIN,
            size=11,
        )

        window.setContentView_(content)
        self._window = window

    def _handle_save_key(self) -> None:
        try:
            value = str(self._key_field.stringValue()) if self._key_field is not None else ""
        except Exception:
            logger.exception("Failed to read the API key field")
            return
        self._on_save_groq_key(value)

    def _do_refresh(self) -> None:
        try:
            if "state" in self._labels:
                self._labels["state"].setStringValue_(self._get_state_text())
            statuses = self._get_permission_statuses()
            if "mic_status" in self._labels:
                self._labels["mic_status"].setStringValue_(statuses.get("microphone", "Microphone: ?"))
            if "accessibility_status" in self._labels:
                self._labels["accessibility_status"].setStringValue_(
                    statuses.get("accessibility", "Accessibility: ?")
                )
            if "stats" in self._labels:
                self._labels["stats"].setStringValue_(self._get_stats_text())
            if "dictation_button" in self._labels:
                self._labels["dictation_button"].setTitle_(self._get_dictation_button_text())
            if "meeting_button" in self._labels:
                self._labels["meeting_button"].setTitle_(self._get_meeting_button_text())
        except Exception:
            logger.exception("Failed to refresh the main window")

    def set_key_status_text(self, text: str) -> None:
        if not self._enabled:
            return

        def _apply():
            if "key_status" in self._labels:
                self._labels["key_status"].setStringValue_(text)

        AppHelper.callAfter(_apply)

    # ------------------------------------------------------------------ #
    # Layout helpers
    # ------------------------------------------------------------------ #
    def _add_label(self, content, text, y, x=_MARGIN, width=None, bold=False, size=13):
        if width is None:
            width = _WINDOW_WIDTH - 2 * _MARGIN
        label = NSTextField.alloc().initWithFrame_(((x, y), (width, _ROW_HEIGHT)))
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBordered_(False)
        label.setDrawsBackground_(False)
        label.setStringValue_(text)
        try:
            font = (
                NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
            )
            label.setFont_(font)
        except Exception:
            pass
        content.addSubview_(label)
        return label

    def _add_section_label(self, content, text, y):
        self._add_label(content, text, y, bold=True, size=13)
        return y - _ROW_HEIGHT

    def _add_button(self, content, title, y, callback, x=_MARGIN, width=140, height=_ROW_HEIGHT):
        button = NSButton.alloc().initWithFrame_(((x, y), (width, height)))
        button.setTitle_(title)
        target = _ActionTarget.alloc().initWithCallback_(callback)
        self._targets.append(target)
        button.setTarget_(target)
        button.setAction_("invoke:")
        content.addSubview_(button)
        return button


def check_accessibility_permission() -> Optional[bool]:
    """Passive, side-effect-free check - never prompts, never blocks."""
    if not _APPKIT_AVAILABLE or AXIsProcessTrusted is None:
        return None
    try:
        return bool(AXIsProcessTrusted())
    except Exception:
        logger.exception("Failed to check Accessibility permission")
        return None
