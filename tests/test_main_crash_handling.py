"""Tests for the paranoid crash-visibility wrapper in voiceflow/main.py.

These exercise the pure-logic helpers directly (escaping, log writing) and
mock out `subprocess.run` for the osascript alert - we never want to
actually invoke osascript during a test run (and it doesn't exist on
Linux anyway).
"""

import voiceflow.main as main_module


def test_applescript_escape_handles_quotes_and_backslashes():
    result = main_module._applescript_escape('He said "hi" and used a \\ backslash')
    assert result == 'He said \\"hi\\" and used a \\\\ backslash'


def test_applescript_escape_flattens_newlines():
    result = main_module._applescript_escape("line one\nline two")
    assert "\n" not in result
    assert result == "line one line two"


def test_write_crash_log_creates_file_with_traceback(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "crash.log"
    monkeypatch.setattr(main_module, "_CRASH_LOG_PATH", log_path)

    try:
        raise ValueError("something broke")
    except ValueError as exc:
        result_path = main_module._write_crash_log("test stage", exc)

    assert result_path == log_path
    assert log_path.exists()
    content = log_path.read_text()
    assert "test stage" in content
    assert "ValueError" in content
    assert "something broke" in content


def test_write_crash_log_appends_on_repeated_failures(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "crash.log"
    monkeypatch.setattr(main_module, "_CRASH_LOG_PATH", log_path)

    for i in range(3):
        try:
            raise RuntimeError(f"failure {i}")
        except RuntimeError as exc:
            main_module._write_crash_log("stage", exc)

    content = log_path.read_text()
    assert content.count("failure 0") == 1
    assert content.count("failure 1") == 1
    assert content.count("failure 2") == 1


def test_show_native_alert_invokes_osascript_with_escaped_text(monkeypatch):
    calls = []
    monkeypatch.setattr(
        main_module.subprocess, "run", lambda *a, **k: calls.append((a, k))
    )
    main_module._show_native_alert('Title with "quotes"', "message text")
    assert len(calls) == 1
    args, kwargs = calls[0]
    command = args[0]
    assert command[0] == "osascript"
    assert '\\"quotes\\"' in command[2]


def test_show_native_alert_never_raises_even_if_osascript_missing(monkeypatch):
    def raise_file_not_found(*a, **k):
        raise FileNotFoundError("no osascript")

    monkeypatch.setattr(main_module.subprocess, "run", raise_file_not_found)
    main_module._show_native_alert("Title", "message")  # must not raise


def test_main_returns_error_code_on_non_darwin(monkeypatch):
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    assert main_module.main() == 1
