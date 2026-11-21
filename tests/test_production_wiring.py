import pytest

from src import main


def test_default_arguments_select_production_mode():
    args = main.build_argument_parser().parse_args([])

    assert args.mock is False


def test_mock_mode_requires_an_explicit_flag():
    args = main.build_argument_parser().parse_args(["--mock"])

    assert args.mock is True


def test_main_factory_wires_nested_operator_graph():
    args = main.build_argument_parser().parse_args(["--mock"])
    operator = main.build_operator(args)
    state_machine = operator.mode_manager

    assert operator.audio_source is not None
    assert operator.vad is not None
    assert operator.speech_recognizer is not None
    assert operator.speech_synthesizer is state_machine.speech_synthesizer
    assert state_machine.llm_provider is not None
    assert state_machine.os_controller is not None
    assert state_machine.document_readers


def test_missing_production_models_fail_with_a_spoken_startup_error(
    monkeypatch, tmp_path
):
    class RecordingSynthesizer:
        def __init__(self):
            self.messages = []

        def speak(self, text, **kwargs):
            self.messages.append(text)

    synthesizer = RecordingSynthesizer()
    monkeypatch.setattr(main, "_create_production_synthesizer", lambda: synthesizer)
    monkeypatch.chdir(tmp_path)

    args = main.build_argument_parser().parse_args([])
    with pytest.raises(FileNotFoundError, match="Whisper"):
        main.build_operator(args)

    assert synthesizer.messages
    assert "Whisper" in synthesizer.messages[0]
