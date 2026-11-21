import pytest
from src.core.state_machine.mode_manager import ModeManager
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockAudioSource, MockVAD, MockSpeechRecognizer, MockSpeechSynthesizer
from src.orchestrator import Orchestrator

@pytest.mark.asyncio
async def test_emergency_stop_aborts_active_tts():
    """Verifies that the emergency stop triggers TTS halt immediately."""
    audio = MockAudioSource()
    vad = MockVAD()
    recognizer = MockSpeechRecognizer()
    tts = MockSpeechSynthesizer()
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    orch = Orchestrator(audio, vad, recognizer, tts, mm)
    
    # 1. Simulate TTS speaking a long sentence
    tts.speak("This is a deliberately long sentence to verify emergency stop behavior.")
    assert tts.is_speaking() is True
    
    # 2. Trigger emergency stop
    recognizer.queue_transcription("stop")
    
    # Spy on tts.stop method
    original_stop = tts.stop
    stop_called = False
    def spy_stop():
        nonlocal stop_called
        stop_called = True
        original_stop()
    tts.stop = spy_stop
    
    await orch.run_single_step()
    
    # 3. Speech stop must have been called
    assert stop_called is True


@pytest.mark.asyncio
async def test_emergency_stop_clears_pending_confirmation():
    """Verifies that emergency stop cancels and clears active safety confirmation gates."""
    audio = MockAudioSource()
    vad = MockVAD()
    recognizer = MockSpeechRecognizer()
    tts = MockSpeechSynthesizer()
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    orch = Orchestrator(audio, vad, recognizer, tts, mm)
    
    # 1. Enter confirmation state
    recognizer.queue_transcription("delete secret.docx")
    await orch.run_single_step()
    assert orch.confirm_state == "action_confirm"
    assert orch.pending_confirm_action is not None
    
    # 2. Trigger emergency stop
    recognizer.queue_transcription("stop")
    await orch.run_single_step()
    
    # 3. Confirmation state must be cleared and reset
    assert orch.confirm_state is None
    assert orch.pending_confirm_action is None
    # Deletion action must not have run
    assert not any(act["action"] == "delete_file" for act in os_ctrl.executed_actions)


@pytest.mark.asyncio
async def test_emergency_stop_resets_dictation_and_reading_modes():
    """Hostile test: Emergency stop command while in Dictation or Reading mode instantly forces return to Command mode."""
    audio = MockAudioSource()
    vad = MockVAD()
    recognizer = MockSpeechRecognizer()
    tts = MockSpeechSynthesizer()
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    orch = Orchestrator(audio, vad, recognizer, tts, mm)
    
    # 1. Switch to Dictation Mode
    mm.set_mode("dictation")
    assert mm.current_mode == "dictation"
    
    # Trigger Emergency Stop
    recognizer.queue_transcription("stop")
    await orch.run_single_step()
    assert mm.current_mode == "command"
    
    # 2. Switch to Reading Mode
    mm.set_mode("reading")
    assert mm.current_mode == "reading"
    
    # Trigger Emergency Stop
    recognizer.queue_transcription("stop")
    await orch.run_single_step()
    assert mm.current_mode == "command"
