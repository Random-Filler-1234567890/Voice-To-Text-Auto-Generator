import re
import threading
import time

from voiceflow.meeting import MeetingNotesSession


class FakeChunkResult:
    def __init__(self, duration_seconds=2.0, wav_bytes=b"fake-wav"):
        self.duration_seconds = duration_seconds
        self.wav_bytes = wav_bytes


class FakeChunkRecorder:
    """Stands in for AudioRecorder for one chunk's worth of recording."""

    def __init__(self, duration_seconds=2.0, raise_on_start=False):
        self.duration_seconds = duration_seconds
        self.raise_on_start = raise_on_start

    def start(self):
        if self.raise_on_start:
            raise RuntimeError("simulated microphone failure")

    def stop(self):
        return FakeChunkResult(duration_seconds=self.duration_seconds)


class FakeTranscriptionService:
    def __init__(self, text="hello world"):
        self.text = text
        self.calls = 0

    def transcribe(self, wav_bytes):
        self.calls += 1
        return self.text


class FakeFormattingService:
    def __init__(self, summary="## Summary\nA test summary.", fail_on_summarize=False):
        self.summary = summary
        self.fail_on_summarize = fail_on_summarize
        self.summarize_calls = 0
        self.clean_calls = 0

    def clean_meeting_segment(self, raw_segment_text):
        self.clean_calls += 1
        return raw_segment_text.strip() + " [cleaned]"

    def summarize_meeting(self, full_transcript):
        self.summarize_calls += 1
        if self.fail_on_summarize:
            raise RuntimeError("summary provider down")
        return self.summary


def wait_until(predicate, timeout=2.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def make_session(tmp_path, recorder_duration=0.01, chunk_seconds=9999.0, **kwargs):
    transcription = kwargs.pop("transcription", None) or FakeTranscriptionService()
    formatting = kwargs.pop("formatting", None) or FakeFormattingService()
    notifications = []
    session = MeetingNotesSession(
        audio_recorder_factory=lambda: FakeChunkRecorder(duration_seconds=recorder_duration),
        transcription_service=transcription,
        formatting_service=formatting,
        chunk_seconds=chunk_seconds,
        notes_dir=tmp_path,
        on_notify=lambda title, msg, level: notifications.append((title, msg, level)),
        **kwargs,
    )
    return session, transcription, formatting, notifications


def test_start_creates_file_with_header(tmp_path):
    session, *_ = make_session(tmp_path)
    file_path = session.start()
    assert file_path.exists()
    content = file_path.read_text()
    assert "Meeting Notes" in content
    session.stop()


def test_process_chunk_appends_timestamped_cleaned_text(tmp_path):
    session, transcription, formatting, _ = make_session(tmp_path, chunk_seconds=9999.0)
    session.start()

    session._process_chunk(b"raw audio bytes")

    content = session.file_path.read_text()
    assert re.search(r"\*\*\[\d{2}:\d{2}:\d{2}\]\*\*", content)
    assert "[cleaned]" in content
    assert session.word_count > 0
    assert formatting.clean_calls == 1
    session.stop()


def test_empty_transcript_chunk_is_skipped(tmp_path):
    session, transcription, formatting, _ = make_session(
        tmp_path, transcription=FakeTranscriptionService(text="   ")
    )
    session.start()
    session._process_chunk(b"raw")
    content = session.file_path.read_text()
    assert formatting.clean_calls == 0
    assert session.word_count == 0
    assert "Meeting Notes" in content  # only the header
    session.stop()


def test_short_chunks_never_get_transcribed(tmp_path):
    session, transcription, formatting, _ = make_session(
        tmp_path, recorder_duration=0.01, chunk_seconds=0.03,
        min_chunk_seconds_to_transcribe=1.5,
    )
    session.start()
    wait_until(lambda: transcription.calls > 0 or not session.is_active, timeout=0.3)
    session.stop()
    assert transcription.calls == 0


def test_stop_generates_summary_when_word_count_high_enough(tmp_path):
    long_text = " ".join(["word"] * 30)
    session, transcription, formatting, _ = make_session(
        tmp_path,
        transcription=FakeTranscriptionService(text=long_text),
        formatting=FakeFormattingService(summary="## Summary\nLong meeting summary."),
        generate_summary=True,
    )
    session.start()
    session._process_chunk(b"raw")
    assert session.word_count > 20

    session.stop()

    assert formatting.summarize_calls == 1
    content = session.file_path.read_text()
    assert "## Summary" in content
    assert content.index("## Summary") < content.index("word word")


def test_stop_skips_summary_when_disabled(tmp_path):
    long_text = " ".join(["word"] * 30)
    session, transcription, formatting, _ = make_session(
        tmp_path,
        transcription=FakeTranscriptionService(text=long_text),
        generate_summary=False,
    )
    session.start()
    session._process_chunk(b"raw")
    session.stop()
    assert formatting.summarize_calls == 0


def test_summary_failure_does_not_lose_raw_notes(tmp_path):
    long_text = " ".join(["word"] * 30)
    session, transcription, formatting, _ = make_session(
        tmp_path,
        transcription=FakeTranscriptionService(text=long_text),
        formatting=FakeFormattingService(fail_on_summarize=True),
        generate_summary=True,
    )
    session.start()
    session._process_chunk(b"raw")
    session.stop()  # must not raise even though summarization fails
    content = session.file_path.read_text()
    assert "word word" in content  # raw segment text survived


def test_is_active_and_elapsed_seconds(tmp_path):
    session, *_ = make_session(tmp_path)
    assert session.is_active is False
    session.start()
    assert session.is_active is True
    time.sleep(0.05)
    assert session.elapsed_seconds() > 0
    session.stop()
    assert session.is_active is False


def test_microphone_failure_marks_session_inactive_and_notifies(tmp_path):
    session, transcription, formatting, notifications = make_session(tmp_path, chunk_seconds=9999.0)
    session._audio_recorder_factory = lambda: FakeChunkRecorder(raise_on_start=True)
    session.start()

    assert wait_until(lambda: not session.is_active, timeout=2.0)
    assert any("microphone" in msg.lower() for _, msg, _ in notifications)


def test_stop_is_idempotent_after_background_failure(tmp_path):
    session, *_ = make_session(tmp_path, chunk_seconds=9999.0)
    session._audio_recorder_factory = lambda: FakeChunkRecorder(raise_on_start=True)
    session.start()
    assert wait_until(lambda: not session.is_active, timeout=2.0)

    # Simulates the app noticing a dead session and calling stop() anyway -
    # must not raise, and must still return the (unfinished) file path.
    file_path = session.stop()
    assert file_path == session.file_path


def test_double_start_raises(tmp_path):
    session, *_ = make_session(tmp_path)
    session.start()
    try:
        session.start()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    session.stop()


def test_stop_without_start_raises(tmp_path):
    session, *_ = make_session(tmp_path)
    try:
        session.stop()
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_concurrent_stop_calls_only_finalize_once(tmp_path):
    # Regression test: a rapid double-click on "Stop Meeting Notes" in the
    # app used to be able to race two stop() calls past the _active check
    # and run summary generation twice. stop() now serializes via an
    # internal lock so only one caller actually finalizes the session.
    long_text = " ".join(["word"] * 30)
    session, transcription, formatting, _ = make_session(
        tmp_path,
        transcription=FakeTranscriptionService(text=long_text),
        generate_summary=True,
    )
    session.start()
    session._process_chunk(b"raw")

    results = []

    def _stop():
        results.append(session.stop())

    threads = [threading.Thread(target=_stop) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(r == session.file_path for r in results)
    assert formatting.summarize_calls == 1
    content = session.file_path.read_text()
    assert content.count("## Summary") == 1
