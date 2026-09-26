"""Helpers to jump the user straight to the relevant macOS privacy settings pane."""

from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger("voiceflow.ui.permissions")

_PANES = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
}


def open_settings_pane(name: str) -> None:
    url = _PANES.get(name)
    if url is None:
        logger.warning("Unknown settings pane requested: %r", name)
        return
    try:
        subprocess.run(["open", url], check=False)
    except Exception:
        logger.exception("Failed to open System Settings pane %r", name)


def open_accessibility_settings() -> None:
    open_settings_pane("accessibility")


def open_microphone_settings() -> None:
    open_settings_pane("microphone")


def open_input_monitoring_settings() -> None:
    open_settings_pane("input_monitoring")
