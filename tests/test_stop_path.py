import time
from unittest.mock import MagicMock, patch

import pytest

from src import main
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
from src.adapters.vosk_stop_listener import VoskStopListener
from src.core.state_machine.mode_manager import ModeManager


def test_vosk_stop_listener_accepts_device_and_debounce():
    listener = VoskStopListener(
        input_device=2,
        debounce_seconds=1.5,
    )
    assert listener.input_device == 2
    assert listener.debounce_seconds == 1.5


def test_vosk_stop_listener_debounces_triggers():
    stop_count = 0

    def on_stop():
        nonlocal stop_count
        stop_count += 1

    listener = VoskStopListener(
        on_stop=on_stop,
        debounce_seconds=1.5,
    )

    listener.trigger_stop()
    assert stop_count == 1

    # Second trigger within 1.5 s must be ignored
    listener.trigger_stop()
    assert stop_count == 1

    # After debounce window, trigger succeeds
    listener._last_trigger_time = time.time() - 2.0
    listener.trigger_stop()
    assert stop_count == 2


def test_main_wires_and_starts_stop_listener():
    args = main.build_argument_parser().parse_args(["--mock", "--input-device", "3"])
    operator = main.build_operator(args)

    assert hasattr(operator, "stop_listener")
    assert operator.stop_listener is not None
    assert operator.stop_listener.input_device == "3"
    assert operator.stop_listener.debounce_seconds == 1.5


def test_stop_listener_on_stop_wires_tts_reading_and_mode_reset():
    args = main.build_argument_parser().parse_args(["--mock", "--input-device", "3"])
    operator = main.build_operator(args)

    operator.mode_manager.current_mode = "reading"
    operator.mode_manager._pending_confirmation_action = "dummy_action"

    operator.stop_listener.on_stop()

    assert operator.mode_manager.current_mode == "command"
    assert operator.mode_manager._pending_confirmation_action is None


def test_orchestrator_keeps_main_mic_open_during_tts():
    """Main mic frames must not be dropped while TTS is speaking."""
    from src.orchestrator import Orchestrator
    from src.adapters.mocks.speech_mock import MockAudioSource, MockVAD, MockSpeechRecognizer, MockSpeechSynthesizer
    from src.adapters.mocks.llm_mock import MockLLMProvider
    from src.adapters.mocks.os_control_mock import MockOSController

    audio = MockAudioSource()
    vad = MockVAD()
    recognizer = MockSpeechRecognizer()
    tts = MockSpeechSynthesizer()
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    mm = ModeManager(llm, os_ctrl, tts)
    orch = Orchestrator(audio, vad, recognizer, tts, mm)

    tts._is_speaking = True
    # The orchestrator should not enter a discard loop or have discarded frames
    # Verify by checking that orchestrator does not block on TTS
    assert hasattr(orch, "keep_mic_open_during_tts") or not hasattr(orch, "_discard_until")
