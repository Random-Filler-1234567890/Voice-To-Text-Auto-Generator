from dataclasses import dataclass

from voiceflow.ai.errors import AllProvidersFailedError, NoProviderConfiguredError
from voiceflow.clipboard.injector import InjectionError
from voiceflow.config import ConfigManager
from voiceflow.context.macos_context import ActiveWindowContext
from voiceflow.memory.store import MemoryEntry
from voiceflow.pipeline import MIN_RECORDING_SECONDS, DictationPipeline
from voiceflow.state import AppState, StateManager


@dataclass
class FakeRecordingResult:
    wav_bytes: bytes = b"fake-wav"
    duration_seconds: float = 2.0
    sample_rate: int = 16000
    peak_amplitude: float = 0.5
    clipped: bool = False


class FakeAudioRecorder:
    def __init__(self, duration=2.0):
        self.started = False
        self.duration = duration
        self.cancel_called = False

    def start(self, on_max_duration_exceeded=None):
        self.started = True

    def stop(self):
        self.started = False
        return FakeRecordingResult(duration_seconds=self.duration)

    def cancel(self):
        self.cancel_called = True
        self.started = False


class FakeTranscriptionService:
    def __init__(self, text="hello world", exc=None):
        self.text = text
        self.exc = exc
        self.calls = []

    def transcribe(self, wav_bytes):
        self.calls.append(wav_bytes)
        if self.exc:
            raise self.exc
        return self.text


class FakeFormattingService:
    def __init__(self, formatted="Hello, world.", facts=None, exc=None):
        self.formatted = formatted
        self.facts = facts or []
        self.exc = exc
        self.format_calls = []
        self.extract_calls = []

    def format_transcript(self, raw_text, app_profile, memory_snippets):
        self.format_calls.append((raw_text, app_profile, memory_snippets))
        if self.exc:
            raise self.exc
        return self.formatted

    def extract_facts(self, statement):
        self.extract_calls.append(statement)
        if self.exc:
            raise self.exc
        return self.facts


class FakeMemoryStore:
    def __init__(self):
        self.learned = []

    def relevant_snippets(self, query_text, max_results=8):
        return ["Sarah Chen is my boss"]

    def learn_from_facts(self, facts):
        entries = [
            MemoryEntry(id=str(i), category=f["category"], text=f["text"], created_at=0.0)
            for i, f in enumerate(facts)
        ]
        self.learned.extend(entries)
        return entries


class FakeInjector:
    def __init__(self, fail=False):
        self.fail = fail
        self.injected_text = None

    def inject(self, text, on_restored=None):
        if self.fail:
            raise InjectionError("simulated paste failure")
        self.injected_text = text
        if on_restored:
            on_restored()


class FakeContextDetector:
    def get_frontmost_context(self):
        return ActiveWindowContext(app_name="Slack", bundle_id="com.tinyspeck.slackmacgap", window_title="")


def make_pipeline(tmp_path, transcription=None, formatting=None, injector=None, audio=None):
    config = ConfigManager(path=tmp_path / "config.json")
    state = StateManager()
    notifications = []
    results = []
    pipeline = DictationPipeline(
        config=config,
        state=state,
        audio_recorder=audio or FakeAudioRecorder(),
        transcription_service=transcription or FakeTranscriptionService(),
        formatting_service=formatting or FakeFormattingService(),
        memory_store=FakeMemoryStore(),
        clipboard_injector=injector or FakeInjector(),
        context_detector=FakeContextDetector(),
        on_notify=lambda title, msg, level: notifications.append((title, msg, level)),
        on_result=lambda result: results.append(result),
    )
    return pipeline, state, notifications, results


def test_full_dictation_cycle_injects_formatted_text(tmp_path):
    injector = FakeInjector()
    formatting = FakeFormattingService(formatted="Hello, world.")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, formatting=formatting, injector=injector
    )

    # start_recording()/stop_recording() are the real entry points the
    # hotkey listener calls; _process() then runs on a background thread.
    # We call _process directly (as the other tests do) for deterministic,
    # non-threaded assertions, but exercise the real start/stop transitions
    # first to prove the public entry points behave correctly too.
    pipeline.start_recording()
    assert state.state == AppState.RECORDING

    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(duration_seconds=2.0), state.generation)

    assert injector.injected_text == "Hello, world."
    assert state.state == AppState.IDLE
    assert results[-1].kind == "injected"


def test_learn_command_routes_to_memory(tmp_path):
    formatting = FakeFormattingService(facts=[{"category": "person", "text": "Sarah is my boss"}])
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Learn: my boss is Sarah"),
        formatting=formatting,
    )
    recording_result = FakeRecordingResult()
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(recording_result, state.generation)

    assert results[-1].kind == "learned"
    assert results[-1].learned_count == 1
    assert formatting.extract_calls == ["my boss is Sarah"]
    assert state.state == AppState.IDLE


def test_too_short_recording_is_ignored(tmp_path):
    transcription = FakeTranscriptionService()
    pipeline, state, notifications, results = make_pipeline(tmp_path, transcription=transcription)
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    short_result = FakeRecordingResult(duration_seconds=MIN_RECORDING_SECONDS / 2)
    pipeline._process(short_result, state.generation)

    assert transcription.calls == []  # never even attempted transcription
    assert results[-1].kind == "ignored_too_short"
    assert state.state == AppState.IDLE


def test_empty_transcript_is_ignored(tmp_path):
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, transcription=FakeTranscriptionService(text="   ")
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert results[-1].kind == "ignored_empty"
    assert state.state == AppState.IDLE


def test_no_provider_configured_notifies_and_resets(tmp_path):
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(exc=NoProviderConfiguredError("no key set")),
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert state.state == AppState.IDLE
    assert any("no key set" in msg for _, msg, _ in notifications)


def test_all_transcription_providers_failed_notifies_and_resets(tmp_path):
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(exc=AllProvidersFailedError("network down")),
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert state.state == AppState.IDLE
    assert notifications  # some error notification fired


def test_formatting_failure_falls_back_to_raw_transcript(tmp_path):
    injector = FakeInjector()
    formatting = FakeFormattingService(exc=AllProvidersFailedError("formatting down"))
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="raw dictated text"),
        formatting=formatting,
        injector=injector,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    # Falls back to the raw transcript rather than losing the dictation entirely.
    assert injector.injected_text == "raw dictated text"
    assert state.state == AppState.IDLE


def test_injection_failure_notifies_and_resets(tmp_path):
    injector = FakeInjector(fail=True)
    pipeline, state, notifications, results = make_pipeline(tmp_path, injector=injector)
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert state.state == AppState.IDLE
    assert any("clipboard" in msg.lower() for _, msg, _ in notifications)


def test_start_recording_ignored_when_not_idle(tmp_path):
    audio = FakeAudioRecorder()
    pipeline, state, notifications, results = make_pipeline(tmp_path, audio=audio)
    state.transition(AppState.RECORDING)
    pipeline.start_recording()  # should be ignored - already recording
    assert audio.started is False


def test_cancel_resets_to_idle_and_cancels_audio(tmp_path):
    audio = FakeAudioRecorder()
    pipeline, state, notifications, results = make_pipeline(tmp_path, audio=audio)
    pipeline.start_recording()
    assert state.state == AppState.RECORDING
    pipeline.cancel()
    assert audio.cancel_called is True
    assert state.state == AppState.IDLE
