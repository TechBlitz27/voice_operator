import pytest
from src.core.state_machine.mode_manager import ModeManager
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.adapters.mocks.speech_mock import MockDocumentReader, MockSpeechSynthesizer


def make_mode_manager():
    return ModeManager(
        llm_provider=MockLLMProvider(),
        os_controller=MockOSController(),
        speech_synthesizer=MockSpeechSynthesizer(),
        document_readers={".pdf": MockDocumentReader(), ".docx": MockDocumentReader()},
    )

def test_mode_transitions():
    """Verifies transitions between Command, Dictation, and Reading modes."""
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts,
                     document_readers={".pdf": MockDocumentReader()})
    
    # 1. Initial Mode must be Command
    assert mm.current_mode == "command"


def test_read_document_uses_reader_content_and_tracks_position():
    reader = MockDocumentReader()
    manager = ModeManager(
        MockLLMProvider(), MockOSController(), MockSpeechSynthesizer(), {".pdf": reader}
    )
    result = manager.route({
        "intent_confidence": 0.9,
        "action": "read_document",
        "target": "guide.pdf",
        "parameters": {},
    })
    assert result["result"]["success"] is True
    assert manager.current_mode == "reading"
    assert manager.reading_chunks == ["Mock document content from guide.pdf."]
    manager.set_mode("command")


def test_read_document_rejects_unsupported_file_type():
    manager = make_mode_manager()
    result = manager.route({
        "intent_confidence": 0.9,
        "action": "read_document",
        "target": "guide.txt",
        "parameters": {},
    })
    assert result["result"]["success"] is False
    
    # 2. Entering Reading Mode
    intent_read = {"intent_confidence": 0.9, "action": "read_document", "target": "guide.pdf", "parameters": {}}
    manager.route(intent_read)
    assert manager.current_mode == "reading"
    
    # 3. Interruption / Stop command in Reading Mode reverts to Command
    res = manager.route_transcript("stop")
    assert res["status"] == "mode_switch"
    assert res["new_mode"] == "command"
    assert manager.current_mode == "command"
    
    # 4. Entering Dictation Mode
    intent_type = {"intent_confidence": 0.9, "action": "type_text", "target": "", "parameters": {}}
    manager.route(intent_type)
    assert manager.current_mode == "dictation"
    
    # 5. Stop dictating reverts to Command
    res = manager.route_transcript("stop dictating")
    assert res["status"] == "mode_switch"
    assert res["new_mode"] == "command"
    assert manager.current_mode == "command"


def test_dictation_mode_bypasses_llm():
    """Verifies that normal text is typed directly and never hits LLM during dictation."""
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    
    # Start dictating
    mm.set_mode("dictation")
    
    # Send a command-like transcript
    res = mm.route_transcript("open notepad")
    
    # It must type the text rather than launching the application
    assert res["status"] == "dictation_typed"
    assert "open notepad" in os_ctrl.typed_inputs
    assert not any(act["action"] == "open_app" for act in os_ctrl.executed_actions)


def test_dictation_mode_edit_commands():
    """Hostile test: Verifies dictation edit shortcuts (undo, delete word, new paragraph) execute properly."""
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    mm.set_mode("dictation")
    
    # 1. Undo command
    res_undo = mm.route_transcript("undo")
    assert res_undo["status"] == "dictation_edit"
    assert res_undo["command"] == "undo"
    assert "ctrl+z" in os_ctrl.typed_inputs
    
    # 2. Delete last word command
    res_del = mm.route_transcript("delete last word")
    assert res_del["status"] == "dictation_edit"
    assert res_del["command"] == "delete_last_word"
    assert "ctrl+backspace" in os_ctrl.typed_inputs
    
    # 3. New paragraph command
    res_para = mm.route_transcript("new paragraph")
    assert res_para["status"] == "dictation_edit"
    assert res_para["command"] == "new_paragraph"
    assert "\n\n" in os_ctrl.typed_inputs

    res_capitalize = mm.route_transcript("capitalize next")
    assert res_capitalize["command"] == "capitalize_next"
    typed = mm.route_transcript("hello")
    assert typed["text"] == "Hello"


def test_dictation_mode_exit_keywords():
    """Verifies that dictation stop and exit keywords switch mode back to command mode."""
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    
    # 1. Stop keyword
    mm.set_mode("dictation")
    res_stop = mm.route_transcript("stop dictating")
    assert res_stop["status"] == "mode_switch"
    assert mm.current_mode == "command"
    
    # 2. Exit keyword
    mm.set_mode("dictation")
    res_exit = mm.route_transcript("exit")
    assert mm.current_mode == "command"


def test_dictation_mode_full_lifecycle_and_intentional_text():
    """Task 5 & 10: Complete dictation state machine test:
    Command Mode -> "Start dictating" -> Dictation Mode -> arbitrary text typed into app (not sent to LLM) -> "Stop dictating" -> Command Mode -> Command executed.
    """
    llm = MockLLMProvider()
    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    
    # 1. Start dictation
    res1 = mm.route_transcript("start dictating")
    assert res1.get("status") in ("completed", "mode_switch")
    assert mm.current_mode == "dictation"
    
    # 2. Dictation utterance 1: "Hello. This is GST website."
    res2 = mm.route_transcript("Hello. This is GST website.")
    assert res2["status"] == "dictation_typed"
    assert any("hello. this is gst website" in t.lower() for t in os_ctrl.typed_inputs)
    assert not any(act["action"] in ("open_app", "close_app", "switch_app", "delete_file") for act in os_ctrl.executed_actions)
    
    # 3. Dictation utterance 2: "That is sports tournament."
    res3 = mm.route_transcript("That is sports tournament.")
    assert res3["status"] == "dictation_typed"
    assert any("that is sports tournament" in t.lower() for t in os_ctrl.typed_inputs)
    assert not any(act["action"] in ("open_app", "close_app", "switch_app", "delete_file") for act in os_ctrl.executed_actions)
    
    # 4. Command-like phrase in dictation mode: "open chrome" -> typed as text, NOT executed
    res4 = mm.route_transcript("open chrome")
    assert res4["status"] == "dictation_typed"
    assert "open chrome" in os_ctrl.typed_inputs
    assert not any(act["action"] == "open_app" for act in os_ctrl.executed_actions)
    
    # 5. Stop dictating
    res5 = mm.route_transcript("stop dictating")
    assert res5["status"] == "mode_switch"
    assert mm.current_mode == "command"
    
    # 6. Subsequent command executed normally
    res6 = mm.route_transcript("open notepad")
    assert mm.current_mode == "command"
    assert any(act["action"] == "open_app" and act["target"] == "notepad" for act in os_ctrl.executed_actions)

