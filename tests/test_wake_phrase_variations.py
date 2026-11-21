import pytest
from src.core.state_machine.mode_manager import ModeManager
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.llm_mock import MockLLMProvider

def test_wake_phrase_variations():
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(
        llm_provider=llm,
        os_controller=os_ctrl,
        speech_synthesizer=tts,
        attention_policy="wake_phrase"
    )
    # Expire initial window
    import time
    mm.attention_until = time.time() - 1.0

    # 1. Comma after wake phrase
    res = mm.route_transcript("Hey Operator, open notepad")
    assert res.get("status") != "dropped_outside_attention_window"
    assert "notepad" in str(os_ctrl.executed_actions)

    # 2. Standalone wake phrase
    mm.attention_until = time.time() - 1.0
    res = mm.route_transcript("Hey Operator")
    assert res.get("status") == "wake_phrase_acknowledged"

    # 3. Ambient speech without wake phrase is dropped
    mm.attention_until = time.time() - 1.0
    res = mm.route_transcript("the weather is nice today")
    assert res.get("status") == "dropped_outside_attention_window"

def test_always_listening_policy():
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(
        llm_provider=llm,
        os_controller=os_ctrl,
        speech_synthesizer=tts,
        attention_policy="always_listening"
    )
    import time
    mm.attention_until = time.time() - 1.0

    # Should execute directly without wake phrase
    res = mm.route_transcript("open chrome")
    assert res.get("status") != "dropped_outside_attention_window"
    assert "chrome" in str(os_ctrl.executed_actions)
