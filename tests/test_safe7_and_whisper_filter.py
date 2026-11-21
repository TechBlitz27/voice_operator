from unittest.mock import MagicMock, patch
import pytest

from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
from src.core.state_machine.mode_manager import ModeManager


def test_wake_phrase_miss_speaks_short_cue():
    """SAFE-7: Utterances dropped outside attention window must speak a short cue."""
    tts = MockSpeechSynthesizer()
    tts.messages = []
    # override speak to record messages
    orig_speak = tts.speak
    tts.speak = lambda msg, **kw: tts.messages.append(msg)

    mm = ModeManager(MockLLMProvider(), MockOSController(), tts, attention_policy="wake_phrase")
    # Expire attention window
    mm.attention_until = 0.0

    res = mm.route_transcript("open notepad")

    assert res["status"] == "dropped_outside_attention_window"
    assert len(tts.messages) > 0, "SAFE-7 violation: Wake-phrase miss dropped silently without spoken cue!"
    assert any("operator" in m.lower() or "catch" in m.lower() for m in tts.messages)


def test_gate_drop_and_low_confidence_speak_short_cue():
    """SAFE-7: Low confidence and gate drops must speak a short cue."""
    tts = MockSpeechSynthesizer()
    tts.messages = []
    tts.speak = lambda msg, **kw: tts.messages.append(msg)

    mm = ModeManager(MockLLMProvider(), MockOSController(), tts, attention_policy="always_listening")

    # 1. Low confidence drop (< 0.8)
    tts.messages.clear()
    res_conf = mm.route({"action": "open_app", "target": "notepad", "intent_confidence": 0.5}, raw_text="open notepad")
    assert res_conf["status"] == "intent_gate_rejected_confidence"
    assert len(tts.messages) > 0, "SAFE-7 violation: Low confidence dropped without spoken cue!"

    # 2. Length gate drop (> 6 words)
    tts.messages.clear()
    res_len = mm.route(
        {"action": "open_app", "target": "notepad", "intent_confidence": 0.95},
        raw_text="open notepad please and do it right now quickly"
    )
    assert res_len["status"] == "intent_gate_rejected_length"
    assert len(tts.messages) > 0, "SAFE-7 violation: Length gate drop without spoken cue!"


def test_whisper_filters_output_equal_to_initial_prompt():
    """STT must filter out Whisper hallucination where output equals initial_prompt."""
    from src.adapters.whisper_stt import WhisperSpeechRecognizer, COMMAND_PROMPT_PREFIX

    with patch("faster_whisper.WhisperModel"):
        stt = WhisperSpeechRecognizer()
        stt._initialized = True
        stt._model = MagicMock()

        # Simulate Whisper returning the initial prompt verbatim
        prompt_text = stt._command_initial_prompt.strip()

        mock_segment = MagicMock()
        mock_segment.text = prompt_text
        mock_segment.avg_logprob = -0.1
        mock_segment.no_speech_prob = 0.05
        mock_info = MagicMock()
        mock_info.language = "en"
        mock_info.language_probability = 0.99

        stt._model.transcribe.return_value = ([mock_segment], mock_info)

        # Transcribe dummy audio
        result = stt.transcribe(b"\x00" * 3200)

        assert result == "", f"Expected initial_prompt hallucination to be filtered out, got '{result}'"
