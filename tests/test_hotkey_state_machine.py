from voiceflow.hotkeys.state_machine import (
    HotkeyConfig,
    HotkeyEvent,
    HotkeyMode,
    HotkeyStateMachine,
)

HOLD_MS = 180
DTAP_MS = 350


def make_machine(mode, scheduler, events):
    config = HotkeyConfig(mode=mode, hold_threshold_ms=HOLD_MS, double_tap_window_ms=DTAP_MS)
    return HotkeyStateMachine(config, on_event=events.append, scheduler=scheduler)


# ---------------------------------------------------------------------- #
# HOLD mode
# ---------------------------------------------------------------------- #
def test_hold_mode_starts_immediately_on_press(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HOLD, fake_scheduler, events)
    m.key_down()
    assert events == [HotkeyEvent.RECORDING_STARTED_HOLD]


def test_hold_mode_stops_on_release(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HOLD, fake_scheduler, events)
    m.key_down()
    m.key_up()
    assert events == [HotkeyEvent.RECORDING_STARTED_HOLD, HotkeyEvent.RECORDING_STOPPED_RELEASE]


def test_hold_mode_ignores_duplicate_press(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HOLD, fake_scheduler, events)
    m.key_down()
    m.key_down()  # duplicate, should be a no-op
    assert events == [HotkeyEvent.RECORDING_STARTED_HOLD]


# ---------------------------------------------------------------------- #
# TOGGLE mode
# ---------------------------------------------------------------------- #
def test_toggle_mode_starts_and_stops_on_press_only(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.TOGGLE, fake_scheduler, events)
    m.key_down()
    m.key_up()  # ignored in toggle mode
    assert events == [HotkeyEvent.RECORDING_STARTED_TOGGLE]
    m.key_down()
    assert events == [
        HotkeyEvent.RECORDING_STARTED_TOGGLE,
        HotkeyEvent.RECORDING_STOPPED_TOGGLE,
    ]


# ---------------------------------------------------------------------- #
# HYBRID mode - hold-to-talk path
# ---------------------------------------------------------------------- #
def test_hybrid_hold_past_threshold_starts_recording(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    assert events == []  # not yet - waiting on the hold-threshold timer
    fake_scheduler.fire_next()  # threshold elapses while key still down
    assert events == [HotkeyEvent.RECORDING_STARTED_HOLD]
    m.key_up()
    assert events == [HotkeyEvent.RECORDING_STARTED_HOLD, HotkeyEvent.RECORDING_STOPPED_RELEASE]


def test_hybrid_quick_tap_alone_is_a_noop(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()  # released before hold threshold -> tap, waiting for a 2nd tap
    assert events == []
    fake_scheduler.fire_next()  # double-tap window expires with no 2nd tap
    assert events == []
    assert m.state == "idle"


def test_hybrid_double_tap_starts_latch(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()  # tap 1
    m.key_down()  # tap 2 within window -> confirms double tap
    assert events == [HotkeyEvent.RECORDING_STARTED_LATCH]
    assert m.state == "latched_recording"


def test_hybrid_latch_then_release_does_not_stop(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()
    m.key_down()  # latched now
    m.key_up()  # releasing the 2nd tap's key must not stop the latch
    assert events == [HotkeyEvent.RECORDING_STARTED_LATCH]
    assert m.state == "latched_recording"


def test_hybrid_double_tap_stops_latch(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()
    m.key_down()  # start latch
    m.key_up()
    # Now perform the stopping double-tap.
    m.key_down()
    m.key_up()
    m.key_down()
    assert events == [HotkeyEvent.RECORDING_STARTED_LATCH, HotkeyEvent.RECORDING_STOPPED_LATCH]
    assert m.state == "idle"


def test_hybrid_lone_tap_while_latched_is_noop(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()
    m.key_down()  # start latch
    m.key_up()

    m.key_down()  # a single tap attempt to stop
    m.key_up()
    fake_scheduler.fire_next()  # window expires, no 2nd tap arrives
    assert events == [HotkeyEvent.RECORDING_STARTED_LATCH]
    assert m.state == "latched_recording"


def test_hybrid_holding_again_while_latched_does_not_stop(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    m.key_up()
    m.key_down()  # start latch
    m.key_up()

    m.key_down()  # user holds again while latched
    fake_scheduler.fire_next()  # hold threshold elapses
    m.key_up()
    assert events == [HotkeyEvent.RECORDING_STARTED_LATCH]
    assert m.state == "latched_recording"


def test_reset_cancels_pending_timer_and_returns_idle(fake_scheduler):
    events = []
    m = make_machine(HotkeyMode.HYBRID, fake_scheduler, events)
    m.key_down()
    assert fake_scheduler.pending_count == 1
    m.reset()
    assert m.state == "idle"
    assert fake_scheduler.pending_count == 0
