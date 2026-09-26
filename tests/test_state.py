from voiceflow.state import AppState, StateManager


def test_starts_idle():
    sm = StateManager()
    assert sm.state == AppState.IDLE


def test_legal_transition_succeeds():
    sm = StateManager()
    assert sm.transition(AppState.RECORDING) is True
    assert sm.state == AppState.RECORDING


def test_illegal_transition_rejected():
    sm = StateManager()
    # Can't go straight from IDLE to FORMATTING.
    assert sm.transition(AppState.FORMATTING) is False
    assert sm.state == AppState.IDLE


def test_full_happy_path_sequence():
    sm = StateManager()
    assert sm.transition(AppState.RECORDING)
    assert sm.transition(AppState.TRANSCRIBING)
    assert sm.transition(AppState.FORMATTING)
    assert sm.transition(AppState.INJECTING)
    assert sm.transition(AppState.IDLE)
    assert sm.state == AppState.IDLE


def test_learning_path():
    sm = StateManager()
    assert sm.transition(AppState.RECORDING)
    assert sm.transition(AppState.TRANSCRIBING)
    assert sm.transition(AppState.LEARNING)
    assert sm.transition(AppState.IDLE)


def test_editing_path():
    sm = StateManager()
    assert sm.transition(AppState.RECORDING)
    assert sm.transition(AppState.TRANSCRIBING)
    assert sm.transition(AppState.EDITING)
    assert sm.transition(AppState.INJECTING)
    assert sm.transition(AppState.IDLE)


def test_meeting_path():
    sm = StateManager()
    assert sm.transition(AppState.MEETING)
    assert sm.transition(AppState.IDLE)


def test_meeting_blocks_normal_recording():
    sm = StateManager()
    assert sm.transition(AppState.MEETING)
    # Can't start a normal dictation while a meeting session is active.
    assert sm.transition(AppState.RECORDING) is False
    assert sm.state == AppState.MEETING


def test_force_idle_always_succeeds_even_from_illegal_state():
    sm = StateManager()
    sm.transition(AppState.RECORDING)
    sm.transition(AppState.TRANSCRIBING)
    sm.transition(AppState.FORMATTING)
    sm.force_idle()
    assert sm.state == AppState.IDLE


def test_listeners_notified_on_transition():
    sm = StateManager()
    events = []
    sm.add_listener(lambda old, new: events.append((old, new)))
    sm.transition(AppState.RECORDING)
    sm.transition(AppState.TRANSCRIBING)
    assert events == [
        (AppState.IDLE, AppState.RECORDING),
        (AppState.RECORDING, AppState.TRANSCRIBING),
    ]


def test_listener_exception_does_not_break_transition():
    sm = StateManager()

    def bad_listener(old, new):
        raise RuntimeError("boom")

    sm.add_listener(bad_listener)
    assert sm.transition(AppState.RECORDING) is True
    assert sm.state == AppState.RECORDING


def test_generation_bumped_on_new_recording():
    sm = StateManager()
    gen1 = sm.new_generation()
    gen2 = sm.new_generation()
    assert gen2 == gen1 + 1
    assert sm.is_current_generation(gen2)
    assert not sm.is_current_generation(gen1)


def test_remove_listener():
    sm = StateManager()
    events = []
    listener = lambda old, new: events.append((old, new))
    sm.add_listener(listener)
    sm.remove_listener(listener)
    sm.transition(AppState.RECORDING)
    assert events == []
