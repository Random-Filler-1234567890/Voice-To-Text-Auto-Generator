"""Frontmost-application detection on macOS.

Uses ``NSWorkspace`` (via PyObjC) for the app name/bundle id - this is
fast (no subprocess spawn) and only requires the app to be running, no
special permission. Window-title enrichment additionally uses the
Accessibility (AX) API, which needs the "Accessibility" permission we
already require for keyboard simulation; if that permission hasn't been
granted yet we silently fall back to app-name-only context instead of
failing the whole dictation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from voiceflow.context.app_profiles import AppProfile, get_profile

logger = logging.getLogger("voiceflow.context")

try:
    from AppKit import NSWorkspace
    from ApplicationServices import (
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        kAXFocusedWindowAttribute,
        kAXTitleAttribute,
    )

    _MACOS_APIS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only off-macOS
    _MACOS_APIS_AVAILABLE = False


@dataclass(frozen=True)
class ActiveWindowContext:
    app_name: str
    bundle_id: str
    window_title: str
    pid: Optional[int] = None


_UNKNOWN_CONTEXT = ActiveWindowContext(app_name="Unknown", bundle_id="", window_title="")


class ActiveAppDetector:
    """Reads the frontmost application's identity and (best-effort) window title."""

    def __init__(self) -> None:
        self._ax_permission_warned = False

    def get_frontmost_context(self) -> ActiveWindowContext:
        if not _MACOS_APIS_AVAILABLE:
            return _UNKNOWN_CONTEXT

        try:
            workspace = NSWorkspace.sharedWorkspace()
            app = workspace.frontmostApplication()
            if app is None:
                return _UNKNOWN_CONTEXT
            app_name = str(app.localizedName() or "Unknown")
            bundle_id = str(app.bundleIdentifier() or "")
            pid = int(app.processIdentifier())
        except Exception:
            logger.exception("Failed to read frontmost application via NSWorkspace")
            return _UNKNOWN_CONTEXT

        window_title = self._read_focused_window_title(pid)
        return ActiveWindowContext(
            app_name=app_name, bundle_id=bundle_id, window_title=window_title, pid=pid
        )

    def _read_focused_window_title(self, pid: int) -> str:
        try:
            ax_app = AXUIElementCreateApplication(pid)
            err, window = AXUIElementCopyAttributeValue(ax_app, kAXFocusedWindowAttribute, None)
            if err != 0 or window is None:
                return ""
            err, title = AXUIElementCopyAttributeValue(window, kAXTitleAttribute, None)
            if err != 0 or title is None:
                return ""
            return str(title)
        except Exception:
            if not self._ax_permission_warned:
                logger.info(
                    "Could not read window title via Accessibility API (permission not "
                    "granted yet, or unsupported app). Falling back to app-name-only "
                    "context. Grant Accessibility access in System Settings for richer "
                    "context detection."
                )
                self._ax_permission_warned = True
            return ""

    def get_profile_for_current_context(
        self, overrides: Optional[dict[str, str]] = None
    ) -> tuple[ActiveWindowContext, AppProfile]:
        context = self.get_frontmost_context()
        profile = get_profile(
            bundle_id=context.bundle_id,
            app_name=context.app_name,
            window_title=context.window_title,
            overrides=overrides,
        )
        return context, profile
