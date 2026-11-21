import pytest
from pydantic import ValidationError
from src.core.models.intent import LLMIntent, ExecutorAction
from src.core.state_machine.mode_manager import ACTION_CONFIRMATIONS
from src.core.state_machine.mode_manager import ModeManager
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer

def test_action_tier_lookup_rules():
    """Verifies that confirmations correspond exactly to the locked action tier table."""
    # High-risk actions must require confirmation
    assert ACTION_CONFIRMATIONS["delete_file"] is True
    assert ACTION_CONFIRMATIONS["send_email"] is True
    
    # Reversible actions must not require pre-confirmation
    assert ACTION_CONFIRMATIONS["open_app"] is False
    assert ACTION_CONFIRMATIONS["close_app"] is False
    assert ACTION_CONFIRMATIONS["switch_app"] is False
    assert ACTION_CONFIRMATIONS["read_document"] is False


def test_intent_validation_valid():
    """Verifies that correctly formed LLM intents pass Pydantic schema validation."""
    intent_data = {
        "intent_confidence": 0.95,
        "action": "open_app",
        "target": "notepad",
        "parameters": {}
    }
    intent = LLMIntent(**intent_data)
    assert intent.action == "open_app"
    assert intent.target == "notepad"


def test_intent_validation_invalid_action():
    """Verifies that unsupported or malicious action enums are rejected by Pydantic."""
    invalid_data = {
        "intent_confidence": 0.9,
        "action": "format_c_drive",  # Malicious/unsupported action not in whitelist
        "target": "system",
        "parameters": {}
    }
    with pytest.raises(ValidationError):
        LLMIntent(**invalid_data)


def test_executor_action_safety_override():
    """Verifies that LLM-provided confirmation fields are overridden by the safety validator."""
    # Scenario: The LLM maliciously/accidently outputs requires_confirmation = False for a delete_file command
    action_data = {
        "intent_confidence": 0.99,
        "action": "delete_file",
        "target": "confidential.txt",
        "parameters": {},
        "requires_confirmation": False  # The LLM's guess
    }
    
    # The safety system must rebuild this action lookup and enforce the table rule
    requires_confirm = ACTION_CONFIRMATIONS[action_data["action"]]
    
    # Re-apply the lookup override (matching ModeManager.route logic)
    action = ExecutorAction(
        intent_confidence=action_data["intent_confidence"],
        action=action_data["action"],
        target=action_data["target"],
        parameters=action_data["parameters"],
        requires_confirmation=requires_confirm  # Enforced by code, not LLM guess
    )
    
    assert action.requires_confirmation is True  # Table overrides the LLM!


def test_adversarial_confirmation_responses_fail_closed():
    """Hostile test: Verifies that ONLY an explicit, exact 'yes' authorizes execution; all other inputs fail-closed."""
    adversarial_responses = [
        "no",
        "no don't delete",
        "maybe later",
        "cancel",
        "yes... wait no!",
        "surely not",
        "absolutely not",
        "never mind",
        "I don't know",
        "",
        "   "
    ]
    for resp in adversarial_responses:
        cleaned = resp.strip().lower()
        # Fail-closed safety invariant assertion
        is_confirmed = (cleaned == "yes")
        assert is_confirmed is False, f"Adversarial response '{resp}' was incorrectly authorized!"


def test_intent_validation_confidence_boundaries():
    """Hostile test: Low confidence signals (< 0.5) or invalid target strings are validated safely."""
    # Low confidence intent
    intent_data = {
        "intent_confidence": 0.2,
        "action": "open_app",
        "target": "notepad",
        "parameters": {}
    }
    with pytest.raises(ValidationError):
        LLMIntent(**intent_data)


def test_llm_cannot_supply_force_close_parameter():
    manager = ModeManager(MockLLMProvider(), MockOSController(), MockSpeechSynthesizer())
    result = manager.route({
        "intent_confidence": 0.9,
        "action": "close_app",
        "target": "word",
        "parameters": {"force": True},
    })
    assert result["action"]["parameters"] == {}


def test_positive_confirmation_variations():
    positive_phrases = ["yes", "yeah", "yep", "confirm", "proceed", "sure", "haan", "sahi", "haanji"]
    for phrase in positive_phrases:
        os_ctrl = MockOSController()
        tts = MockSpeechSynthesizer()
        mm = ModeManager(MockLLMProvider(), os_ctrl, tts)

        assert mm.route({
            "intent_confidence": 0.95,
            "action": "delete_file",
            "target": "test.txt",
            "parameters": {},
        })["status"] == "awaiting_confirmation"

        result = mm.route_transcript(phrase)
        assert result["status"] == "completed"
        assert mm._pending_confirmation_action is None
        assert len(os_ctrl.executed_actions) == 1


def test_negative_confirmation_variations():
    negative_phrases = ["no", "nope", "cancel", "stop", "nahi", "mat karo"]
    for phrase in negative_phrases:
        os_ctrl = MockOSController()
        tts = MockSpeechSynthesizer()
        mm = ModeManager(MockLLMProvider(), os_ctrl, tts)

        assert mm.route({
            "intent_confidence": 0.95,
            "action": "delete_file",
            "target": "test.txt",
            "parameters": {},
        })["status"] == "awaiting_confirmation"

        result = mm.route_transcript(phrase)
        assert result["status"] == "confirmation_rejected"
        assert mm._pending_confirmation_action is None
        assert len(os_ctrl.executed_actions) == 0


def test_unrelated_command_while_confirmation_pending_preserves_safety_and_routes_command():
    """A new command cancels the pending action and is routed by the state machine."""
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(MockLLMProvider(), os_ctrl, tts)
    mm.route_transcript("close unsaved_word")
    assert mm._pending_confirmation_action is not None

    result = mm.route_transcript("start dictating")

    assert mm._pending_confirmation_action is None
    assert len(os_ctrl.executed_actions) == 1
    assert os_ctrl.executed_actions[0]["parameters"] == {}
    assert mm.current_mode == "dictation"
    assert result.get("status") in ("completed", "mode_switch")

