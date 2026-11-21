import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from src.core.interfaces.speech import SpeechSynthesizer
from src.core.state_machine.mode_manager import ModeManager
from src.orchestrator import Orchestrator

DEFAULT_GGUF_MODEL = "qwen2.5-3b-instruct.Q4_K_M.gguf"


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Voice Accessibility Operator")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--mock",
        action="store_true",
        help="Use simulated adapters for development instead of the default production adapters",
    )
    mode.add_argument(
        "--production", "-p", "--prod",
        action="store_true",
        help="Run with real Windows APIs and offline ML models (the default)",
    )
    parser.add_argument("--list-audio-devices", action="store_true",
                        help="List available recording devices and exit")
    parser.add_argument("--input-device",
                        help="Recording device index or unique name substring")
    parser.add_argument("--audio-file",
                        help="Path to a recorded WAV/MP3 file to use as the audio input stream")
    parser.add_argument("--keep-audio", action="store_true",
                        help="Save recorded audio chunks to logs/audio/")
    parser.add_argument(
        "--policy",
        choices=["wake_phrase", "always_listening", "push_to_talk"],
        default="wake_phrase",
        help="Attention policy: 'wake_phrase' (default) or 'always_listening'",
    )
    parser.add_argument(
        "--always-listening", "-a",
        action="store_true",
        help="Execute commands directly without needing 'Hey Operator' wake phrase",
    )
    return parser


def _create_production_synthesizer() -> SpeechSynthesizer:
    from src.adapters.sapi_tts import SAPITTS

    return SAPITTS()


def _validate_production_assets() -> None:
    required_files = {
        "Whisper": Path("models/whisper-base/model.bin"),
        "Silero": Path("models/silero_vad.onnx"),
        "Vosk": Path("models/vosk-model-small-en-us-0.15/am/final.mdl"),
        "GGUF": Path("models") / DEFAULT_GGUF_MODEL,
    }
    missing = [f"{name}: {path}" for name, path in required_files.items() if not path.is_file()]

    for package in ("faster_whisper", "onnxruntime", "vosk", "llama_cpp"):
        try:
            installed = importlib.util.find_spec(package) is not None
        except (ImportError, ValueError):
            installed = False
        if not installed:
            missing.append(f"required package: {package}")

    if missing:
        raise FileNotFoundError(
            "Required offline production assets are missing: " + "; ".join(missing)
        )


def _build_mock_operator(args: argparse.Namespace) -> Orchestrator:
    from src.adapters.mocks.llm_mock import MockLLMProvider
    from src.adapters.mocks.os_control_mock import MockOSController
    from src.adapters.mocks.speech_mock import (
        MockAudioSource,
        MockDocumentReader,
        MockSpeechRecognizer,
        MockSpeechSynthesizer,
        MockVAD,
    )

    if args.audio_file:
        from src.adapters.recorded_audio import RecordedAudioSource

        audio = RecordedAudioSource(audio_path=args.audio_file)
    else:
        audio = MockAudioSource()

    synthesizer = MockSpeechSynthesizer()
    reader = MockDocumentReader()
    mode_manager = ModeManager(
        llm_provider=MockLLMProvider(),
        os_controller=MockOSController(),
        speech_synthesizer=synthesizer,
        document_readers={".pdf": reader, ".docx": reader},
        attention_policy=args.policy,
    )

    from src.adapters.vosk_stop_listener import VoskStopListener

    def on_stop() -> None:
        synthesizer.stop()
        if hasattr(mode_manager, "_stop_reading_playback"):
            mode_manager._stop_reading_playback()
        mode_manager.set_mode("command")
        mode_manager.clear_pending_confirmation()

    stop_listener = VoskStopListener(
        on_stop=on_stop,
        tts_synthesizer=synthesizer,
        input_device=args.input_device,
        debounce_seconds=1.5,
    )

    return Orchestrator(
        audio_source=audio,
        vad=MockVAD(),
        speech_recognizer=MockSpeechRecognizer(),
        speech_synthesizer=synthesizer,
        mode_manager=mode_manager,
        keep_audio=args.keep_audio,
        stop_listener=stop_listener,
    )


def _build_production_operator(args: argparse.Namespace) -> Orchestrator:
    synthesizer = _create_production_synthesizer()
    try:
        _validate_production_assets()

        from src.adapters.docx_reader import DOCXReader
        from src.adapters.llamacpp_provider import LlamaCppLLMProvider
        from src.adapters.pdf_reader import PDFReader
        from src.adapters.silero_vad import SileroVAD
        from src.adapters.whisper_stt import WhisperSpeechRecognizer
        from src.adapters.windows_control import WindowsOSController

        if args.audio_file:
            from src.adapters.recorded_audio import RecordedAudioSource

            audio = RecordedAudioSource(audio_path=args.audio_file)
        else:
            from src.adapters.sounddevice_audio import SounddeviceAudio

            audio = SounddeviceAudio(
                device=args.input_device,
                speech_synthesizer=synthesizer,
            )
            audio.start_stream(calibrate=True)

        mode_manager = ModeManager(
            llm_provider=LlamaCppLLMProvider(),
            os_controller=WindowsOSController(),
            speech_synthesizer=synthesizer,
            document_readers={".pdf": PDFReader(), ".docx": DOCXReader()},
            attention_policy=args.policy,
        )

        from src.adapters.vosk_stop_listener import VoskStopListener

        def on_stop() -> None:
            synthesizer.stop()
            if hasattr(mode_manager, "_stop_reading_playback"):
                mode_manager._stop_reading_playback()
            mode_manager.set_mode("command")
            mode_manager.clear_pending_confirmation()

        stop_listener = VoskStopListener(
            on_stop=on_stop,
            tts_synthesizer=synthesizer,
            input_device=args.input_device,
            debounce_seconds=1.5,
        )
        try:
            stop_listener.start()
        except Exception as e:
            print(f"[MAIN] Warning: Could not start VoskStopListener: {e}")

        return Orchestrator(
            audio_source=audio,
            vad=SileroVAD(),
            speech_recognizer=WhisperSpeechRecognizer(model_size="base"),
            speech_synthesizer=synthesizer,
            mode_manager=mode_manager,
            keep_audio=args.keep_audio,
            stop_listener=stop_listener,
        )
    except (FileNotFoundError, ImportError, RuntimeError) as error:
        synthesizer.speak(f"Startup failed. {error}", interruptible=False)
        raise


def build_operator(args: argparse.Namespace) -> Orchestrator:
    """Build the complete operator graph; production adapters are the default."""
    if args.mock:
        return _build_mock_operator(args)
    return _build_production_operator(args)


async def main() -> None:
    args = build_argument_parser().parse_args()

    if args.list_audio_devices:
        from src.adapters.sounddevice_audio import SounddeviceAudio

        devices = SounddeviceAudio.list_input_devices()
        if not devices:
            print("No recording devices were found. Check Windows microphone permissions.")
            return
        print("Available recording devices:")
        for device in devices:
            print(
                f"  [{device['index']}] {device['name']} "
                f"({device['host_api']}; {device['channels']} channel(s), "
                f"{device['default_sample_rate']} Hz)"
            )
        return

    print("====================================================")
    print("        AI Task Operator for Accessibility          ")
    print("====================================================")
    if args.mock:
        print("[INIT] Launching in MOCK mode. Use only for development.")
    else:
        print("[INIT] Launching in PRODUCTION mode with offline models...")
    operator = build_operator(args)
    print("====================================================\n")
    await operator.main_loop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting operator.")
        sys.exit(0)
