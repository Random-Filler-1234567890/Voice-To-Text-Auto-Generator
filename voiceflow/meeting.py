"""Meeting Notes mode: continuous, chunked recording that builds a running,
timestamped Markdown transcript instead of a single paste-once dictation.

Design: record in fixed-size chunks (default 20s). Each chunk is
transcribed and lightly cleaned (filler words removed, punctuated) the
moment it finishes, then appended to the notes file on disk immediately -
so if anything crashes mid-meeting, everything up to that point is already
safely saved. Recording the next chunk only starts after the previous
chunk's transcription call returns, trading a small (typically 1-3 second,
API-latency-bound) gap between chunks for a much simpler, more robust
implementation with no concurrent-ordering complexity.

This intentionally does NOT go through the pipeline's per-app formatting
profile - a meeting isn't "dictating into an app", it's an ongoing
transcript, so it gets its own dedicated cleanup prompt
(``FormattingService.clean_meeting_segment``).
"""

from __future__ import annotations

import datetime
import logging
import threading
from pathlib import Path
from typing import Callable, Optional

from voiceflow.paths import MEETING_NOTES_DIR

logger = logging.getLogger("voiceflow.meeting")


class MeetingNotesSession:
    def __init__(
        self,
        audio_recorder_factory: Callable[[], object],
        transcription_service,
        formatting_service,
        chunk_seconds: float = 20.0,
        min_chunk_seconds_to_transcribe: float = 1.5,
        generate_summary: bool = True,
        notes_dir: Path | None = None,
        on_notify: Optional[Callable[[str, str, str], None]] = None,
    ) -> None:
        self._audio_recorder_factory = audio_recorder_factory
        self._transcription = transcription_service
        self._formatting = formatting_service
        self._chunk_seconds = chunk_seconds
        self._min_chunk_seconds = min_chunk_seconds_to_transcribe
        self._generate_summary = generate_summary
        self._notes_dir = notes_dir or MEETING_NOTES_DIR
        self._on_notify = on_notify or (lambda title, msg, level: None)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._file_path: Optional[Path] = None
        self._start_time: Optional[datetime.datetime] = None
        self._segment_count = 0
        self._word_count = 0
        self._active = False
        self._stop_lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def file_path(self) -> Optional[Path]:
        return self._file_path

    @property
    def word_count(self) -> int:
        return self._word_count

    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return (datetime.datetime.now() - self._start_time).total_seconds()

    def start(self) -> Path:
        if self._active:
            raise RuntimeError("A meeting notes session is already active")

        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._start_time = datetime.datetime.now()
        filename = self._start_time.strftime("Meeting %Y-%m-%d %H-%M.md")
        self._file_path = self._notes_dir / filename
        self._segment_count = 0
        self._word_count = 0
        self._stop_event.clear()

        header = (
            f"# Meeting Notes - {self._start_time.strftime('%A, %B %d, %Y at %I:%M %p')}\n\n"
        )
        self._file_path.write_text(header, encoding="utf-8")

        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="voiceflow-meeting")
        self._thread.start()
        logger.info("Meeting notes session started -> %s", self._file_path)
        return self._file_path

    def stop(self) -> Path:
        if self._file_path is None:
            raise RuntimeError("This session was never started")

        # Guards against two threads calling stop() at once (e.g. a rapid
        # double-click on "Stop" before the first call's async cleanup has
        # finished) racing past the _active check and both running the
        # summary-generation step below - only the first caller through
        # this lock actually finalizes the session.
        with self._stop_lock:
            if not self._active:
                # Either the background loop already exited on its own
                # (e.g. a mic error), or another thread already finished
                # stopping it - nothing left to do, report where we got to.
                return self._file_path
            self._stop_event.set()
            if self._thread is not None:
                self._thread.join(timeout=self._chunk_seconds + 30)
            self._active = False

            if self._generate_summary and self._word_count > 20:
                self._append_summary()

        logger.info(
            "Meeting notes session stopped: %d segments, %d words -> %s",
            self._segment_count,
            self._word_count,
            self._file_path,
        )
        return self._file_path

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                recorder = self._audio_recorder_factory()
                recorder.start()
            except Exception:
                logger.exception("Meeting notes: failed to start audio chunk")
                self._on_notify(
                    "VoiceFlow",
                    "Meeting notes stopped unexpectedly: couldn't access the microphone.",
                    "error",
                )
                self._active = False
                return

            finished_early = self._stop_event.wait(self._chunk_seconds)

            try:
                result = recorder.stop()
            except Exception:
                logger.exception("Meeting notes: failed to stop audio chunk")
                self._on_notify(
                    "VoiceFlow", "Meeting notes stopped unexpectedly: recording error.", "error"
                )
                self._active = False
                return

            if result.duration_seconds >= self._min_chunk_seconds:
                self._process_chunk(result.wav_bytes)

            if finished_early:
                break
        # Normal, user-requested stop (finished_early above) falls through
        # to here rather than returning early; stop() itself flips _active
        # to False after this thread is joined.

    def _process_chunk(self, wav_bytes: bytes) -> None:
        try:
            raw_text = self._transcription.transcribe(wav_bytes)
        except Exception:
            logger.exception("Meeting notes: transcription failed for a chunk")
            return

        if not raw_text or not raw_text.strip():
            return

        try:
            cleaned = self._formatting.clean_meeting_segment(raw_text)
        except Exception:
            logger.warning("Meeting notes: cleanup failed for a chunk, using raw text")
            cleaned = raw_text

        cleaned = cleaned.strip()
        if not cleaned:
            return

        self._segment_count += 1
        self._word_count += len(cleaned.split())
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._append_to_file(f"**[{timestamp}]** {cleaned}\n\n")

    def _append_to_file(self, text: str) -> None:
        if self._file_path is None:
            return
        try:
            with open(self._file_path, "a", encoding="utf-8") as fh:
                fh.write(text)
        except OSError:
            logger.exception("Meeting notes: failed to append to notes file")

    def _append_summary(self) -> None:
        try:
            full_text = self._file_path.read_text(encoding="utf-8")
        except OSError:
            logger.exception("Meeting notes: failed to read notes file for summarization")
            return

        try:
            summary = self._formatting.summarize_meeting(full_text)
        except Exception:
            logger.warning("Meeting notes: summary generation failed; raw notes are still saved")
            return

        try:
            header_end = full_text.index("\n\n") + 2
            new_content = full_text[:header_end] + summary.strip() + "\n\n---\n\n" + full_text[header_end:]
            self._file_path.write_text(new_content, encoding="utf-8")
        except (OSError, ValueError):
            logger.exception("Meeting notes: failed to write summary into notes file")
