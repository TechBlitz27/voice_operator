import time

import pytest

from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import (
    MockAudioSource,
    MockSpeechRecognizer,
    MockSpeechSynthesizer,
    MockVAD,
)
from src.core.state_machine.mode_manager import ModeManager
from src.orchestrator import Orchestrator


def _manager(os_control, synthesizer):
    return ModeManager(
        MockLLMProvider(),
        os_control,
        synthesizer,
        attention_policy="always_listening",
    )


def _delete_intent():
    return {
        "intent_confidence": 0.95,
        "action": "delete_file",
        "target": "secret.txt",
        "parameters": {},
    }


def test_non_exact_negative_confirmation_does_not_cancel_or_confirm():
    os_control = MockOSController()
    manager = _manager(os_control, MockSpeechSynthesizer())
    assert manager.route(_delete_intent())["status"] == "awaiting_confirmation"

    result = manager.route_transcript("no I am not sure")

    assert result["status"] != "completed"
    assert manager._pending_confirmation_action is None
    assert os_control.executed_actions == []


@pytest.mark.asyncio
async def test_yes_after_confirmation_timeout_does_not_execute():
    os_control = MockOSController()
    synthesizer = MockSpeechSynthesizer()
    manager = _manager(os_control, synthesizer)
    recognizer = MockSpeechRecognizer()
    operator = Orchestrator(
        MockAudioSource(), MockVAD(), recognizer, synthesizer, manager
    )

    recognizer.queue_transcription("delete secret.txt")
    assert (await operator.run_single_step())["status"] == "awaiting_confirmation"
    manager._pending_confirmation_time = time.time() - 7

    recognizer.queue_transcription("yes")
    result = await operator.run_single_step()

    assert result["status"] == "confirmation_timed_out"
    assert os_control.executed_actions == []


@pytest.mark.asyncio
async def test_next_command_after_confirmation_is_processed():
    os_control = MockOSController()
    synthesizer = MockSpeechSynthesizer()
    manager = _manager(os_control, synthesizer)
    recognizer = MockSpeechRecognizer()
    operator = Orchestrator(
        MockAudioSource(), MockVAD(), recognizer, synthesizer, manager
    )

    recognizer.queue_transcription("delete secret.txt")
    assert (await operator.run_single_step())["status"] == "awaiting_confirmation"
    recognizer.queue_transcription("yes")
    assert (await operator.run_single_step())["status"] == "completed"
    assert manager._pending_confirmation_action is None
    recognizer.queue_transcription("open notepad")

    result = await operator.run_single_step()

    assert result["status"] == "completed"
    actions = [action["action"] for action in os_control.executed_actions]
    assert actions == ["delete_file", "open_app"]
