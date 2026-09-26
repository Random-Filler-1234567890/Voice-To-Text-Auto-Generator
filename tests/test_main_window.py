"""Only the platform-independent guarantees of main_window.py are testable
here: that it degrades to a harmless no-op everywhere AppKit isn't
available (which is always true in this Linux test environment), never
raising during construction or from any public method. The actual AppKit
window-building code (_build_window, _add_label, etc.) requires a real
macOS display and cannot be exercised in this sandbox.
"""

from voiceflow.ui.main_window import MainWindowController, check_accessibility_permission


def _make_controller(**overrides):
    defaults = dict(
        get_state_text=lambda: "state",
        get_permission_statuses=lambda: {},
        get_stats_text=lambda: "stats",
        get_dictation_button_text=lambda: "Start Dictation",
        get_meeting_button_text=lambda: "Start Meeting Notes",
        on_toggle_dictation=lambda: None,
        on_toggle_meeting=lambda: None,
        on_test_microphone=lambda: None,
        on_open_settings_pane=lambda name: None,
        on_save_groq_key=lambda key: None,
    )
    defaults.update(overrides)
    return MainWindowController(**defaults)


def test_construction_never_touches_appkit():
    # Must not raise even off-macOS, since __init__ only stores callbacks.
    controller = _make_controller()
    assert controller is not None


def test_show_is_a_safe_noop_without_appkit():
    controller = _make_controller()
    controller.show()  # must not raise


def test_refresh_is_a_safe_noop_without_appkit():
    controller = _make_controller()
    controller.refresh()  # must not raise


def test_set_key_status_text_is_a_safe_noop_without_appkit():
    controller = _make_controller()
    controller.set_key_status_text("hello")  # must not raise


def test_check_accessibility_permission_returns_none_without_appkit():
    assert check_accessibility_permission() is None
