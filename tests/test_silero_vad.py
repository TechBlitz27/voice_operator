import wave
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from src.adapters.silero_vad import SileroVAD


def test_silero_vad_speech_versus_silence():
    """Verifies that silence chunks yield False and real speech chunks yield True."""
    vad = SileroVAD()
    
    # 1. Create a quiet silence chunk (zeros)
    silence_chunk = np.zeros(512, dtype=np.int16).tobytes()
    for _ in range(10):
        assert not vad.is_speech(silence_chunk)
        
    # 2. Test speech detection using real voice chunk from test audio
    with wave.open("tests/audio/voice_operator_test_commands.wav", "rb") as wf:
        wf.setpos(8000)
        # Feed 3 speech frames (hysteresis requires 3 frames >= 0.50)
        vad.is_speech(wf.readframes(512))
        vad.is_speech(wf.readframes(512))
        assert vad.is_speech(wf.readframes(512))


def test_silero_vad_white_noise_and_static_hum():
    """Hostile test: Pure white noise or background fan hum must NOT trigger speech false positives."""
    vad = SileroVAD()
    np.random.seed(42)
    
    # Low-amplitude white noise (amplitude RMS ~50-100) representing laptop fan / mic static
    for _ in range(20):
        white_noise = np.random.randint(-100, 100, 512, dtype=np.int16).tobytes()
        assert not vad.is_speech(white_noise)


def test_silero_vad_hysteresis():
    """Synthetic test: Hysteresis requires 3 consecutive frames >= 0.5 to start speech,
    and ends speech only after 500 ms below 0.35.
    """
    vad = SileroVAD()
    vad.reset_state()
    dummy_frame = np.zeros(512, dtype=np.int16).tobytes()

    # 1. Mock get_speech_prob to return [0.6, 0.6, 0.4] -> Should NOT start speech (needs 3 consecutive)
    with patch.object(vad, "get_speech_prob", side_effect=[0.60, 0.60, 0.40]):
        assert not vad.is_speech(dummy_frame)  # frame 1 (1 consecutive)
        assert not vad.is_speech(dummy_frame)  # frame 2 (2 consecutive)
        assert not vad.is_speech(dummy_frame)  # frame 3 drops to 0.40 -> reset counter
        assert not vad.in_speech

    # 2. 3 consecutive frames >= 0.50 -> Speech starts
    vad.reset_state()
    with patch.object(vad, "get_speech_prob", side_effect=[0.55, 0.70, 0.85]):
        assert not vad.is_speech(dummy_frame)  # 1
        assert not vad.is_speech(dummy_frame)  # 2
        assert vad.is_speech(dummy_frame)      # 3: Speech triggered!
        assert vad.in_speech

    # 3. Drop below 0.35: Hysteresis holds speech active until 500 ms (16 frames @ 32ms) have elapsed
    # 10 frames below 0.35 = 320 ms (< 500 ms) -> Still in speech
    with patch.object(vad, "get_speech_prob", return_value=0.20):
        for i in range(10):
            assert vad.is_speech(dummy_frame), f"Frame {i} should remain in speech within 500ms hangover"
            assert vad.in_speech

    # 4. Another 6 frames below 0.35 (total 16 frames = 512 ms >= 500 ms) -> Speech ends
    with patch.object(vad, "get_speech_prob", return_value=0.20):
        for _ in range(5):
            vad.is_speech(dummy_frame)
        # 16th frame below 0.35 ends speech
        res = vad.is_speech(dummy_frame)
        assert not res
        assert not vad.in_speech


def test_silero_vad_min_length_and_max_cap():
    """Synthetic test: Enforce minimum speech length of 300 ms and 15 s hard cap."""
    vad = SileroVAD()
    vad.reset_state()
    dummy_frame = np.zeros(512, dtype=np.int16).tobytes()

    # Case A: Short burst (< 300 ms): 3 speech frames (96 ms) followed by 16 silence frames (512 ms)
    # Total speech duration = 96 ms + 512 ms? No, speech frames count = 3 + 16 = 19 frames = 608 ms.
    # For a real short burst: 3 speech frames (96 ms) + 5 silence frames, ending:
    vad.reset_state()
    # Trigger speech: 3 frames @ 0.80
    with patch.object(vad, "get_speech_prob", return_value=0.80):
        vad.is_speech(dummy_frame)
        vad.is_speech(dummy_frame)
        vad.is_speech(dummy_frame)
        assert vad.in_speech
        assert not vad.is_valid_speech  # 96 ms < 300 ms

    # Case B: After reaching >= 300 ms (~10 frames = 320 ms), is_valid_speech becomes True
    with patch.object(vad, "get_speech_prob", return_value=0.80):
        for _ in range(7):
            vad.is_speech(dummy_frame)
        assert vad.is_valid_speech  # 10 frames = 320 ms >= 300 ms

    # Case C: 15 s hard cap (15.0 s / 0.032 s = ~469 frames) forces speech end
    vad.reset_state()
    with patch.object(vad, "get_speech_prob", return_value=0.85):
        # Trigger speech
        for _ in range(3):
            vad.is_speech(dummy_frame)
        assert vad.in_speech

        # Feed 468 more frames (total 471 frames * 32ms = 15.072 s > 15 s)
        for _ in range(468):
            vad.is_speech(dummy_frame)
        assert not vad.in_speech, "Speech must end after 15 s cap"


def test_silero_vad_missing_model_fails_loudly():
    """Verifies that missing ONNX model raises FileNotFoundError and does NOT silently degrade."""
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="Silero VAD ONNX model is missing"):
            SileroVAD(model_path="non_existent/path/silero.onnx")


def test_silero_vad_empty_or_short_input():
    """Verifies that empty audio or null inputs safely return False without exceptions."""
    vad = SileroVAD()
    assert not vad.is_speech(b"")
    assert not vad.is_speech(None)
    assert vad.get_speech_prob(b"") == 0.0
