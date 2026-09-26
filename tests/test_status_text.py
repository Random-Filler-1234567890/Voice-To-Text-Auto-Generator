from voiceflow.state import AppState
from voiceflow.ui.status_text import (
    format_permission_row,
    format_permission_status,
    format_stats_line,
    format_state_line,
)


def test_format_state_line_covers_every_state():
    for state in AppState:
        line = format_state_line(state)
        assert line.strip()
        assert state.name  # sanity


def test_format_state_line_idle():
    assert "Idle" in format_state_line(AppState.IDLE)


def test_format_state_line_recording():
    assert "Recording" in format_state_line(AppState.RECORDING)


def test_format_permission_status_true():
    assert format_permission_status(True) == "Granted"


def test_format_permission_status_false():
    assert format_permission_status(False) == "Not granted"


def test_format_permission_status_none():
    assert format_permission_status(None) == "Not checked yet"


def test_format_permission_row_granted():
    row = format_permission_row("Microphone", True)
    assert "Microphone" in row
    assert "Granted" in row
    assert "[OK]" in row


def test_format_permission_row_denied():
    row = format_permission_row("Microphone", False)
    assert "[X]" in row
    assert "Not granted" in row


def test_format_permission_row_unknown():
    row = format_permission_row("Microphone", None)
    assert "[?]" in row


def test_format_stats_line_no_dictations():
    assert format_stats_line(0, 0, 0.0) == "No dictations yet"


def test_format_stats_line_with_data():
    line = format_stats_line(2000, 5, 45.0)
    assert "2,000 words dictated" in line
    assert "45 min saved" in line
    assert "5 facts learned" in line


def test_format_stats_line_omits_minutes_when_negligible():
    line = format_stats_line(10, 0, 0.2)
    assert "min saved" not in line
