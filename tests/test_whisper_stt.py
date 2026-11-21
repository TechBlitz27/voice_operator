import pytest
from unittest.mock import MagicMock, patch
from src.adapters.whisper_stt import WhisperSpeechRecognizer


def test_whisper_stt_transcription_valid():
    """Verifies that the Whisper adapter transcribes and joins segments correctly with task='transcribe'."""
    mock_model = MagicMock()
    
    mock_segment1 = MagicMock()
    mock_segment1.text = "Open"
    mock_segment1.avg_logprob = -0.2
    mock_segment1.no_speech_prob = 0.05
    mock_segment2 = MagicMock()
    mock_segment2.text = "Chrome."
    mock_segment2.avg_logprob = -0.15
    mock_segment2.no_speech_prob = 0.05
    mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], MagicMock(language="en", language_probability=0.98))
    mock_model.detect_language.return_value = ("en", 0.99, [("en", 0.99)])
    
    with patch("os.path.exists", return_value=True), patch("faster_whisper.WhisperModel", return_value=mock_model):
        recognizer = WhisperSpeechRecognizer(model_size="small", language="en")
        assert recognizer._initialized is True
        
        audio_data = b"\x00" * 32000  # 1s
        text = recognizer.transcribe(audio_data)
        
        assert text == "Open Chrome."
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["task"] == "transcribe", "Must never translate; task must be 'transcribe'"
        assert kwargs["condition_on_previous_text"] is False
        assert kwargs["vad_filter"] is False


def test_whisper_stt_missing_model_fails_loudly():
    """Requirement 6: If model file is missing, do not fall back to console input(). Fail loudly."""
    with patch("os.path.exists", return_value=False):
        with pytest.raises(FileNotFoundError, match="Whisper STT model missing"):
            WhisperSpeechRecognizer(model_size="non_existent_model_xyz")


def test_whisper_hallucination_gate_logprob_and_no_speech():
    """Requirement 4: Drop results where avg_logprob < -1.0 or no_speech_prob > 0.6."""
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("en", 0.95, [("en", 0.95)])
    
    # Case A: Low logprob (< -1.0)
    seg_low_logprob = MagicMock()
    seg_low_logprob.text = "Random whisper hallucination"
    seg_low_logprob.avg_logprob = -1.25  # < -1.0
    seg_low_logprob.no_speech_prob = 0.1
    mock_model.transcribe.return_value = ([seg_low_logprob], None)
    
    with patch("os.path.exists", return_value=True), patch("faster_whisper.WhisperModel", return_value=mock_model):
        recognizer = WhisperSpeechRecognizer(model_size="small")
        audio_data = b"\x00" * 32000
        result = recognizer.transcribe(audio_data)
        assert result == "", "Must drop result when avg_logprob < -1.0"

    # Case B: High no_speech_prob (> 0.6)
    seg_high_no_speech = MagicMock()
    seg_high_no_speech.text = "Open Chrome"
    seg_high_no_speech.avg_logprob = -0.2
    seg_high_no_speech.no_speech_prob = 0.85  # > 0.6
    mock_model.transcribe.return_value = ([seg_high_no_speech], None)

    with patch("os.path.exists", return_value=True), patch("faster_whisper.WhisperModel", return_value=mock_model):
        recognizer = WhisperSpeechRecognizer(model_size="small")
        result = recognizer.transcribe(audio_data)
        assert result == "", "Must drop result when no_speech_prob > 0.6"


def test_whisper_hallucination_gate_blacklist_command_vs_dictation():
    """Requirement 4: Blacklist phrases dropped in command mode, but allowed in dictation mode."""
    mock_model = MagicMock()
    mock_model.detect_language.return_value = ("en", 0.95, [("en", 0.95)])
    
    seg = MagicMock()
    seg.text = "Thank you."
    seg.avg_logprob = -0.1
    seg.no_speech_prob = 0.05
    mock_model.transcribe.return_value = ([seg], None)

    with patch("os.path.exists", return_value=True), patch("faster_whisper.WhisperModel", return_value=mock_model):
        recognizer = WhisperSpeechRecognizer(model_size="small")
        audio_data = b"\x00" * 32000

        # Command mode: blacklisted -> dropped
        recognizer.set_mode("command")
        assert recognizer.transcribe(audio_data) == ""

        # Dictation mode: allowed through
        recognizer.set_mode("dictation")
        assert recognizer.transcribe(audio_data) == "Thank you."


def test_whisper_language_detection_and_fallback():
    """Requirement 1: Detects language on first 3s; accepts only if prob >= 0.7 and in allowed list."""
    mock_model = MagicMock()
    
    seg = MagicMock()
    seg.text = "kholo notepad"
    seg.avg_logprob = -0.1
    seg.no_speech_prob = 0.05
    mock_model.transcribe.return_value = ([seg], None)

    with patch("os.path.exists", return_value=True), patch("faster_whisper.WhisperModel", return_value=mock_model):
        recognizer = WhisperSpeechRecognizer(model_size="small", languages=["en", "hi"])
        audio_data = b"\x00" * 64000  # 2s
        
        # Scenario A: Hindi with high confidence (0.85 >= 0.70) -> accepted
        mock_model.detect_language.return_value = ("hi", 0.85, [("hi", 0.85)])
        recognizer.transcribe(audio_data)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["language"] == "hi"

        # Scenario B: French (not in allowed list ["en", "hi"]) -> falls back to "en"
        mock_model.detect_language.return_value = ("fr", 0.92, [("fr", 0.92)])
        recognizer.transcribe(audio_data)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["language"] == "en"

        # Scenario C: Hindi with low confidence (0.50 < 0.70) -> falls back to "en"
        mock_model.detect_language.return_value = ("hi", 0.50, [("hi", 0.50)])
        recognizer.transcribe(audio_data)
        _, kwargs = mock_model.transcribe.call_args
        assert kwargs["language"] == "en"
