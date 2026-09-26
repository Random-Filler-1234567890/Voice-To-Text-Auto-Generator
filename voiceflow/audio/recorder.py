"""In-memory audio capture.

Audio is streamed straight from ``sounddevice``'s callback into a list of
numpy frames held in RAM and encoded to a WAV byte-string with the stdlib
``wave`` module when recording stops - there is no temp file and no disk
I/O on the hot path, which is where most of the "feels instant" quality of
a dictation tool comes from. (We intentionally use ``wave`` instead of
``scipy.io.wavfile`` - it's stdlib, has zero extra dependency weight, and
produces an identical linear-PCM WAV file, which is all the Whisper APIs
need.)
"""

from __future__ import annotations

import io
import logging
import threading
import time
import wave
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    import sounddevice as sd
except (ImportError, OSError):  # pragma: no cover - exercised only off-macOS
    sd = None

logger = logging.getLogger("voiceflow.audio")


class MicrophoneUnavailableError(RuntimeError):
    """Raised when the configured input device can't be opened."""


@dataclass
class RecordingResult:
    wav_bytes: bytes
    duration_seconds: float
    sample_rate: int
    peak_amplitude: float  # 0.0-1.0, useful for a live "is it hearing me" meter
    clipped: bool  # true if audio hit 0dBFS - warn the user their mic gain is too hot


class AudioRecorder:
    """Records mono PCM audio from the default (or configured) input device."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        device: Optional[int] = None,
        max_recording_seconds: int = 120,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._device = device
        self._max_seconds = max_recording_seconds

        self._stream: Optional["sd.InputStream"] = None
        self._frames: list[np.ndarray] = []
        self._frames_lock = threading.Lock()
        self._recording = False
        self._start_time = 0.0
        self._peak = 0.0
        self._watchdog: Optional[threading.Timer] = None
        self._on_max_duration_exceeded = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def list_input_devices(self) -> list[dict]:
        if sd is None:
            return []
        devices = []
        try:
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) > 0:
                    devices.append({"index": idx, "name": info.get("name", f"Device {idx}")})
        except Exception:
            logger.exception("Failed to enumerate audio devices")
        return devices

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            logger.warning("Audio stream status: %s", status)
        with self._frames_lock:
            self._frames.append(indata.copy())
        chunk_peak = float(np.max(np.abs(indata))) if indata.size else 0.0
        if chunk_peak > self._peak:
            self._peak = chunk_peak

    def start(self, on_max_duration_exceeded=None) -> None:
        if sd is None:
            raise MicrophoneUnavailableError(
                "sounddevice is not available on this platform/installation."
            )
        if self._recording:
            logger.warning("start() called while already recording; ignoring")
            return

        with self._frames_lock:
            self._frames = []
        self._peak = 0.0
        self._on_max_duration_exceeded = on_max_duration_exceeded

        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="float32",
                device=self._device,
                callback=self._callback,
            )
            self._stream.start()
        except Exception as exc:
            logger.exception("Failed to open input stream")
            raise MicrophoneUnavailableError(str(exc)) from exc

        self._recording = True
        self._start_time = time.monotonic()

        if self._max_seconds > 0:
            self._watchdog = threading.Timer(self._max_seconds, self._on_watchdog_fired)
            self._watchdog.daemon = True
            self._watchdog.start()

        logger.info(
            "Recording started (device=%s, rate=%d, channels=%d)",
            self._device,
            self._sample_rate,
            self._channels,
        )

    def _on_watchdog_fired(self) -> None:
        logger.warning("Max recording duration (%ds) exceeded, auto-stopping", self._max_seconds)
        if self._on_max_duration_exceeded is not None:
            try:
                self._on_max_duration_exceeded()
            except Exception:
                logger.exception("max_duration_exceeded callback raised")

    def current_level(self) -> float:
        """Instantaneous peak level (0.0-1.0) for a live waveform/meter UI."""
        return self._peak

    def stop(self) -> RecordingResult:
        if not self._recording:
            raise RuntimeError("stop() called while not recording")

        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None

        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            logger.exception("Error closing audio stream")
        finally:
            self._stream = None
            self._recording = False

        duration = time.monotonic() - self._start_time

        with self._frames_lock:
            frames = self._frames
            self._frames = []

        if frames:
            audio = np.concatenate(frames, axis=0)
        else:
            audio = np.zeros((0, self._channels), dtype="float32")

        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        clipped = peak >= 0.999

        wav_bytes = self._encode_wav(audio)

        logger.info(
            "Recording stopped: %.2fs, peak=%.3f, clipped=%s, bytes=%d",
            duration,
            peak,
            clipped,
            len(wav_bytes),
        )

        return RecordingResult(
            wav_bytes=wav_bytes,
            duration_seconds=duration,
            sample_rate=self._sample_rate,
            peak_amplitude=peak,
            clipped=clipped,
        )

    def cancel(self) -> None:
        """Abort a recording without producing a result (e.g. user error / too short)."""
        if not self._recording:
            return
        if self._watchdog is not None:
            self._watchdog.cancel()
            self._watchdog = None
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            logger.exception("Error closing audio stream during cancel")
        finally:
            self._stream = None
            self._recording = False
            with self._frames_lock:
                self._frames = []
        logger.info("Recording cancelled")

    def _encode_wav(self, audio: np.ndarray) -> bytes:
        int16_audio = np.clip(audio, -1.0, 1.0)
        int16_audio = (int16_audio * 32767).astype(np.int16)

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self._channels)
            wav_file.setsampwidth(2)  # int16
            wav_file.setframerate(self._sample_rate)
            wav_file.writeframes(int16_audio.tobytes())
        return buffer.getvalue()
