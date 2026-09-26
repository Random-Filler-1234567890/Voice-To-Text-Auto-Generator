import pytest

from voiceflow.clipboard.injector import ClipboardInjector, InjectionError


class FakeClipboard:
    def __init__(self, initial=""):
        self.contents = initial
        self.copy_calls = []

    def copy(self, text):
        self.copy_calls.append(text)
        self.contents = text

    def paste(self):
        return self.contents


class FailingCopyClipboard(FakeClipboard):
    def copy(self, text):
        raise RuntimeError("clipboard unavailable")


class FakeKeySimulator:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = 0

    def send_paste_shortcut(self):
        self.calls += 1
        if self.should_fail:
            raise RuntimeError("keystroke simulation failed")


def test_inject_copies_pastes_and_schedules_restore(fake_scheduler):
    clipboard = FakeClipboard(initial="original clipboard text")
    key_sim = FakeKeySimulator()
    injector = ClipboardInjector(
        backend=clipboard, key_simulator=key_sim, scheduler=fake_scheduler, restore_delay_ms=250
    )

    injector.inject("dictated text")

    assert clipboard.contents == "dictated text"
    assert key_sim.calls == 1
    assert fake_scheduler.pending_count == 1


def test_restore_timer_puts_original_clipboard_back(fake_scheduler):
    clipboard = FakeClipboard(initial="original clipboard text")
    injector = ClipboardInjector(
        backend=clipboard, key_simulator=FakeKeySimulator(), scheduler=fake_scheduler
    )
    injector.inject("dictated text")
    assert clipboard.contents == "dictated text"

    fake_scheduler.fire_next()
    assert clipboard.contents == "original clipboard text"


def test_on_restored_callback_fires_after_restore(fake_scheduler):
    clipboard = FakeClipboard(initial="original")
    injector = ClipboardInjector(
        backend=clipboard, key_simulator=FakeKeySimulator(), scheduler=fake_scheduler
    )
    restored = []
    injector.inject("new text", on_restored=lambda: restored.append(True))
    fake_scheduler.fire_next()
    assert restored == [True]


def test_copy_failure_raises_injection_error(fake_scheduler):
    injector = ClipboardInjector(
        backend=FailingCopyClipboard(),
        key_simulator=FakeKeySimulator(),
        scheduler=fake_scheduler,
    )
    with pytest.raises(InjectionError):
        injector.inject("dictated text")


def test_keystroke_failure_restores_immediately_and_raises(fake_scheduler):
    clipboard = FakeClipboard(initial="original")
    key_sim = FakeKeySimulator(should_fail=True)
    injector = ClipboardInjector(backend=clipboard, key_simulator=key_sim, scheduler=fake_scheduler)

    with pytest.raises(InjectionError):
        injector.inject("dictated text")

    # Clipboard should have been restored right away since paste never happened.
    assert clipboard.contents == "original"
    # No restore timer should be left pending since we already restored inline.
    assert fake_scheduler.pending_count == 0


def test_unreadable_original_clipboard_does_not_block_injection(fake_scheduler):
    class UnreadableClipboard(FakeClipboard):
        def paste(self):
            raise RuntimeError("binary clipboard data")

    clipboard = UnreadableClipboard()
    injector = ClipboardInjector(
        backend=clipboard, key_simulator=FakeKeySimulator(), scheduler=fake_scheduler
    )
    # Should not raise even though we couldn't snapshot the original clipboard.
    injector.inject("dictated text")
    assert clipboard.contents == "dictated text"
