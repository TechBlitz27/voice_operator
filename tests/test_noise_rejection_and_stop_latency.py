import time
import pytest
import numpy as np
from unittest.mock import MagicMock

from src.core.state_machine.mode_manager import ModeManager
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
from src.adapters.vosk_stop_listener import VoskStopListener


def test_30_non_command_noise_clips_rejection():
    """Release Gate: 30 non-command noise clips (TV, ambient speech, keyboard) must yield ZERO false actions."""
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(
        llm_provider=llm,
        os_controller=os_ctrl,
        speech_synthesizer=tts,
        attention_policy="wake_phrase"
    )

    # Expire initial startup attention window so we are strictly testing ambient noise rejection
    mm.attention_until = time.time() - 1.0

    non_command_transcripts = [
        # Ambient conversation
        "could you pass the salt please",
        "did you see that game last night",
        "i think it is going to rain this evening",
        "what time does the train arrive",
        "can i get a cup of coffee",
        "where did i leave my car keys",
        "she said she would call back later",
        "we need to buy more groceries tomorrow",
        "how was your weekend",
        "the meeting is scheduled for three o'clock",
        # TV / Media dialogue
        "breaking news reports from around the world",
        "welcome back to our evening broadcast",
        "the detective entered the dark room slowly",
        "subscribe to our channel for more videos",
        "and that is the final score of the championship",
        "in tonight's episode we investigate",
        "stay tuned for our special weather forecast",
        "thank you for watching our show",
        "this program was brought to you by our sponsors",
        "coming up next on channel four",
        # Background / typing / nonsensical noise
        "click clack typing on keyboard",
        "cough cough clearing throat",
        "shh listening to the radio",
        "humming a random tune",
        "paper rustling on the desk",
        "chair squeaking in the background",
        "distant traffic honking outside",
        "footsteps walking down the hallway",
        "telephone ringing in another room",
        "air conditioner humming steadily"
    ]

    assert len(non_command_transcripts) == 30, f"Must have 30 clips, got {len(non_command_transcripts)}"

    executed_actions = 0
    for clip in non_command_transcripts:
        res = mm.route_transcript(clip)
        if res.get("status") in ("completed", "dictation_typed", "dictation_edit"):
            executed_actions += 1

    assert executed_actions == 0, f"False actions on noise must be 0, but got {executed_actions}!"
    assert len(os_ctrl.executed_actions) == 0, "No OS actions may be triggered by background noise!"


def test_stop_latency_under_300ms():
    """Release Gate: Emergency stop must execute and abort active reading in under 300 ms."""
    tts = MockSpeechSynthesizer()
    stop_called = False

    def on_stop_cb():
        nonlocal stop_called
        stop_called = True

    listener = VoskStopListener(
        on_stop=on_stop_cb,
        tts_synthesizer=tts,
        hotkey="ctrl+alt+space"
    )

    t0 = time.perf_counter()
    listener.trigger_stop()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    assert stop_called is True
    assert elapsed_ms < 300.0, f"Stop latency must be under 300 ms, measured: {elapsed_ms:.2f} ms"
