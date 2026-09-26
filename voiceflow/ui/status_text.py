"""Pure-logic text formatting for the status window and menu.

Split out from main_window.py specifically so this logic - unlike the
actual AppKit widget code - can be unit tested on any platform.
"""

from __future__ import annotations

from typing import Optional

from voiceflow.state import AppState

STATE_DISPLAY = {
    AppState.IDLE: ("🎙", "Idle - ready to dictate"),
    AppState.RECORDING: ("🔴", "Recording..."),
    AppState.TRANSCRIBING: ("⏳", "Transcribing..."),
    AppState.FORMATTING: ("✍️", "Formatting..."),
    AppState.INJECTING: ("📋", "Pasting..."),
    AppState.LEARNING: ("🧠", "Learning that fact..."),
    AppState.EDITING: ("🪄", "Rewriting..."),
    AppState.MEETING: ("🗒️", "Recording meeting notes..."),
    AppState.ERROR: ("⚠️", "Something went wrong - check the log"),
}


def format_state_line(state: AppState) -> str:
    emoji, text = STATE_DISPLAY.get(state, ("🎙", state.value.capitalize()))
    return f"{emoji}  {text}"


def format_permission_status(granted: Optional[bool]) -> str:
    """``granted`` is True/False once checked, or None if not checked yet."""
    if granted is None:
        return "Not checked yet"
    return "Granted" if granted else "Not granted"


def format_permission_row(label: str, granted: Optional[bool]) -> str:
    if granted is None:
        symbol = "?"
    elif granted:
        symbol = "OK"
    else:
        symbol = "X"
    return f"[{symbol}] {label}: {format_permission_status(granted)}"


def format_stats_line(total_words: int, total_facts: int, minutes_saved: float) -> str:
    if total_words == 0:
        return "No dictations yet"
    minutes_part = f" - ~{minutes_saved:.0f} min saved" if minutes_saved >= 1 else ""
    return f"{total_words:,} words dictated{minutes_part} - {total_facts} facts learned"
