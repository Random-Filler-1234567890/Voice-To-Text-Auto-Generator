import wave
import io

import numpy as np
import pytest

from voiceflow.audio.recorder import AudioRecorder, MicrophoneUnavailableError


def test_encode_wav_produces_valid_playable_wav():
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    # A simple synthetic sine-ish buffer standing in for real mic input.
    audio = np.linspace(-0.5, 0.5, 1600, dtype=np.float32).reshape(-1, 1)

    wav_bytes = recorder._encode_wav(audio)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2  # int16
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 1600


def test_encode_wav_clips_out_of_range_samples():
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    audio = np.array([[2.0], [-2.0], [0.0]], dtype=np.float32)  # out-of-range on purpose

    wav_bytes = recorder._encode_wav(audio)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
        samples = np.frombuffer(raw, dtype=np.int16)
        assert samples[0] == 32767  # clipped to max int16
        assert samples[1] == -32767  # clipped to min (post *32767 rounding)
        assert samples[2] == 0


def test_encode_wav_handles_empty_audio():
    recorder = AudioRecorder(sample_rate=16000, channels=1)
    audio = np.zeros((0, 1), dtype=np.float32)
    wav_bytes = recorder._encode_wav(audio)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        assert wf.getnframes() == 0


def test_list_input_devices_returns_empty_list_without_sounddevice(monkeypatch):
    import voiceflow.audio.recorder as recorder_module

    monkeypatch.setattr(recorder_module, "sd", None)
    recorder = AudioRecorder()
    assert recorder.list_input_devices() == []


def test_start_without_sounddevice_surfaces_the_real_import_error(monkeypatch):
    # Regression test: a report of "sounddevice is not available on this
    # device/installation" with no further detail turned out to be
    # untraceable precisely because the real underlying ImportError/OSError
    # was being silently discarded. The raised error must now include it.
    import voiceflow.audio.recorder as recorder_module

    monkeypatch.setattr(recorder_module, "sd", None)
    monkeypatch.setattr(
        recorder_module, "_IMPORT_ERROR", "OSError: dlopen failed, wrong architecture"
    )
    recorder = AudioRecorder()
    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        recorder.start()
    assert "wrong architecture" in str(exc_info.value)


def test_start_without_sounddevice_and_no_captured_error_still_gives_actionable_message(
    monkeypatch,
):
    import voiceflow.audio.recorder as recorder_module

    monkeypatch.setattr(recorder_module, "sd", None)
    monkeypatch.setattr(recorder_module, "_IMPORT_ERROR", None)
    recorder = AudioRecorder()
    with pytest.raises(MicrophoneUnavailableError) as exc_info:
        recorder.start()
    assert "rebuild" in str(exc_info.value).lower()
