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
    def __init__(self, formatted="Hello, world.", facts=None, exc=None, rewritten="Rewritten text."):
        self.formatted = formatted
        self.facts = facts or []
        self.exc = exc
        self.rewritten = rewritten
        self.format_calls = []
        self.extract_calls = []
        self.rewrite_calls = []

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

    def rewrite_text(self, instruction, target_text):
        self.rewrite_calls.append((instruction, target_text))
        if self.exc:
            raise self.exc
        return self.rewritten


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


class FakeClipboardReader:
    def __init__(self, text=""):
        self.text = text

    def paste(self):
        return self.text


class FakeHistory:
    def __init__(self):
        self.records = []

    def record(self, text, app_name=""):
        self.records.append((text, app_name))


class FakeStats:
    def __init__(self):
        self.dictation_word_counts = []
        self.facts_learned = 0

    def record_dictation(self, word_count):
        self.dictation_word_counts.append(word_count)

    def record_fact_learned(self):
        self.facts_learned += 1


def make_pipeline(
    tmp_path,
    transcription=None,
    formatting=None,
    injector=None,
    audio=None,
    clipboard_reader=None,
    history=None,
    stats=None,
):
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
        clipboard_reader=clipboard_reader,
        history=history,
        stats=stats,
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


def test_silent_recording_skips_transcription_and_notifies(tmp_path):
    transcription = FakeTranscriptionService()
    pipeline, state, notifications, results = make_pipeline(tmp_path, transcription=transcription)
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    silent_result = FakeRecordingResult(peak_amplitude=0.0)
    pipeline._process(silent_result, state.generation)

    assert transcription.calls == []  # never even attempted transcription - saves an API call
    assert results[-1].kind == "ignored_silent"
    assert state.state == AppState.IDLE
    assert any("microphone" in msg.lower() for _, msg, _ in notifications)


def test_quiet_but_audible_recording_still_gets_transcribed(tmp_path):
    # Only near-total silence should short-circuit - a quietly-spoken but
    # genuinely audible recording must still go through transcription.
    transcription = FakeTranscriptionService(text="a quiet whisper")
    injector = FakeInjector()
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, transcription=transcription, injector=injector
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    quiet_result = FakeRecordingResult(peak_amplitude=0.05)
    pipeline._process(quiet_result, state.generation)

    assert len(transcription.calls) == 1
    assert results[-1].kind == "injected"


def test_clipped_empty_transcript_mentions_clipping(tmp_path):
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, transcription=FakeTranscriptionService(text="")
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    clipped_result = FakeRecordingResult(peak_amplitude=0.5, clipped=True)
    pipeline._process(clipped_result, state.generation)

    assert results[-1].kind == "ignored_empty"
    assert any("clipping" in msg.lower() for _, msg, _ in notifications)


def test_empty_transcript_without_clipping_stays_quiet(tmp_path):
    # No audio-quality issue detected - don't nag the user over an ordinary
    # brief/ambiguous utterance that just happened to transcribe empty.
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, transcription=FakeTranscriptionService(text="")
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    result = FakeRecordingResult(peak_amplitude=0.5, clipped=False)
    pipeline._process(result, state.generation)

    assert results[-1].kind == "ignored_empty"
    assert notifications == []


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


def test_start_recording_ignored_during_meeting(tmp_path):
    audio = FakeAudioRecorder()
    pipeline, state, notifications, results = make_pipeline(tmp_path, audio=audio)
    state.transition(AppState.MEETING)
    pipeline.start_recording()
    assert audio.started is False
    assert state.state == AppState.MEETING


# ---------------------------------------------------------------------- #
# "Edit:"/"Rewrite:" voice command
# ---------------------------------------------------------------------- #
def test_edit_command_rewrites_clipboard_and_injects(tmp_path):
    injector = FakeInjector()
    clipboard_reader = FakeClipboardReader(text="hey whats up")
    formatting = FakeFormattingService(rewritten="Hey, what's up?")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Edit: make this more formal"),
        formatting=formatting,
        injector=injector,
        clipboard_reader=clipboard_reader,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert formatting.rewrite_calls == [("make this more formal", "hey whats up")]
    assert injector.injected_text == "Hey, what's up?"
    assert results[-1].kind == "edited"
    assert state.state == AppState.IDLE


def test_edit_command_with_empty_clipboard_is_rejected(tmp_path):
    formatting = FakeFormattingService()
    clipboard_reader = FakeClipboardReader(text="   ")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Rewrite: make this formal"),
        formatting=formatting,
        clipboard_reader=clipboard_reader,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert formatting.rewrite_calls == []
    assert state.state == AppState.IDLE
    assert any("clipboard" in msg.lower() for _, msg, _ in notifications)


def test_edit_command_without_instruction_falls_back_to_dictation(tmp_path):
    # "Edit:" with nothing after it isn't a usable instruction - treat the
    # whole utterance as normal dictation instead of a no-op edit command.
    injector = FakeInjector()
    formatting = FakeFormattingService(formatted="Edit:")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Edit:"),
        formatting=formatting,
        injector=injector,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert formatting.rewrite_calls == []
    assert results[-1].kind == "injected"


def test_edit_command_injection_failure_falls_back_to_clipboard(tmp_path):
    injector = FakeInjector(fail=True)
    clipboard_reader = FakeClipboardReader(text="original text")
    formatting = FakeFormattingService(rewritten="Rewritten.")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Edit: fix this"),
        formatting=formatting,
        injector=injector,
        clipboard_reader=clipboard_reader,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert state.state == AppState.IDLE
    assert results[-1].kind == "injection_failed"


# ---------------------------------------------------------------------- #
# History + stats recording
# ---------------------------------------------------------------------- #
def test_successful_dictation_records_history_and_stats(tmp_path):
    injector = FakeInjector()
    history = FakeHistory()
    stats = FakeStats()
    formatting = FakeFormattingService(formatted="Hello there friend")
    pipeline, state, notifications, results = make_pipeline(
        tmp_path, formatting=formatting, injector=injector, history=history, stats=stats
    )
    pipeline.start_recording()  # populates _captured_context via FakeContextDetector
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert history.records == [("Hello there friend", "Slack")]
    assert stats.dictation_word_counts == [3]


def test_learn_command_records_stats_per_fact(tmp_path):
    stats = FakeStats()
    formatting = FakeFormattingService(
        facts=[
            {"category": "person", "text": "Sarah is my boss"},
            {"category": "vocabulary", "text": "ACME means a widget company"},
        ]
    )
    pipeline, state, notifications, results = make_pipeline(
        tmp_path,
        transcription=FakeTranscriptionService(text="Learn: my boss is Sarah, ACME is a widget company"),
        formatting=formatting,
        stats=stats,
    )
    state.new_generation()
    state.transition(AppState.RECORDING)
    state.transition(AppState.TRANSCRIBING)
    pipeline._process(FakeRecordingResult(), state.generation)

    assert stats.facts_learned == 2
