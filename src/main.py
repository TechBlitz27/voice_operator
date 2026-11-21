import asyncio
import sys
import argparse
from src.core.state_machine.mode_manager import ModeManager
from src.orchestrator import Orchestrator

async def main():
    parser = argparse.ArgumentParser(description="Voice Accessibility Operator")
    parser.add_argument(
        "--production", "-p", "--prod",
        action="store_true", 
        help="Run with real production Windows APIs and offline ML models"
    )
    parser.add_argument("--list-audio-devices", action="store_true",
                        help="List available recording devices and exit")
    parser.add_argument("--input-device",
                        help="Recording device index or unique name substring (production mode only)")
    parser.add_argument("--audio-file",
                        help="Path to a recorded WAV/MP3 file to use as the audio input stream")
    parser.add_argument("--keep-audio", action="store_true",
                        help="Save recorded audio chunks to logs/audio/")
    parser.add_argument(
        "--policy",
        choices=["wake_phrase", "always_listening", "push_to_talk"],
        default="wake_phrase",
        help="Attention policy: 'wake_phrase' (default) or 'always_listening'"
    )
    parser.add_argument(
        "--always-listening", "-a",
        action="store_true",
        help="Execute commands directly without needing 'Hey Operator' wake phrase"
    )
    args = parser.parse_args()

    if args.list_audio_devices:
        from src.adapters.sounddevice_audio import SounddeviceAudio
        devices = SounddeviceAudio.list_input_devices()
        if not devices:
            print("No recording devices were found. Check Windows microphone permissions.")
            return
        print("Available recording devices:")
        for device in devices:
            print(f"  [{device['index']}] {device['name']} "
                  f"({device['host_api']}; {device['channels']} channel(s), "
                  f"{device['default_sample_rate']} Hz)")
        return

    print("====================================================")
    print("        AI Task Operator for Accessibility          ")
    print("====================================================")
    print("Available Commands:")
    print(" - 'open Notepad' / 'launch Word' / 'open document.pdf'")
    print(" - 'close Word' / 'close unsaved_word' (for dialog safety test)")
    print(" - 'switch to Chrome'")
    print(" - 'delete note.txt' (requires safety confirmation)")
    print(" - 'send email to john@example.com' (requires safety confirmation)")
    print(" - 'read guide.pdf' (starts Reading Mode)")
    print(" - 'start dictating' (starts Dictation Mode)")
    print(" - 'undo' / 'undo last action'")
    policy = "always_listening" if args.always_listening else args.policy
    print("====================================================")
    if policy == "wake_phrase":
        print("Attention Mode: WAKE PHRASE (Say 'Hey Operator, <command>' or 'Hey Operator' first)")
        print("                Tip: Run with --always-listening to execute commands directly without wake phrase.")
    else:
        print("Attention Mode: ALWAYS LISTENING (All spoken commands execute directly)")
    print("====================================================\n")

    if args.production:
        print("[INIT] Launching in PRODUCTION mode using real Windows & SAPI5 adapters...")
        from src.adapters.sapi_tts import SAPITTS
        from src.adapters.windows_control import WindowsOSController
        from src.adapters.silero_vad import SileroVAD
        from src.adapters.whisper_stt import WhisperSpeechRecognizer
        from src.adapters.llamacpp_provider import LlamaCppLLMProvider
        from src.adapters.pdf_reader import PDFReader
        from src.adapters.docx_reader import DOCXReader

        if args.audio_file:
            from src.adapters.recorded_audio import RecordedAudioSource
            audio = RecordedAudioSource(audio_path=args.audio_file)
        else:
            from src.adapters.sounddevice_audio import SounddeviceAudio
            audio = SounddeviceAudio(device=args.input_device)

        vad = SileroVAD()
        recognizer = WhisperSpeechRecognizer()
        synthesizer = SAPITTS()
        llm = LlamaCppLLMProvider()
        os_control = WindowsOSController()
        document_readers = {".pdf": PDFReader(), ".docx": DOCXReader()}
    else:
        print("[INIT] Launching in MOCK mode using simulated interfaces...")
        from src.adapters.mocks.speech_mock import MockAudioSource, MockVAD, MockSpeechRecognizer, MockSpeechSynthesizer, MockDocumentReader
        from src.adapters.mocks.llm_mock import MockLLMProvider
        from src.adapters.mocks.os_control_mock import MockOSController

        if args.audio_file:
            from src.adapters.recorded_audio import RecordedAudioSource
            audio = RecordedAudioSource(audio_path=args.audio_file)
        else:
            audio = MockAudioSource()

        vad = MockVAD()
        recognizer = MockSpeechRecognizer()
        synthesizer = MockSpeechSynthesizer()
        llm = MockLLMProvider()
        os_control = MockOSController()
        mock_reader = MockDocumentReader()
        document_readers = {".pdf": mock_reader, ".docx": mock_reader}


    mode_manager = ModeManager(
        llm_provider=llm,
        os_controller=os_control,
        speech_synthesizer=synthesizer,
        document_readers=document_readers,
        attention_policy=policy,
    )

    orchestrator = Orchestrator(
        audio_source=audio,
        vad=vad,
        speech_recognizer=recognizer,
        speech_synthesizer=synthesizer,
        mode_manager=mode_manager,
        keep_audio=args.keep_audio
    )

    # Start main loop
    await orchestrator.main_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting operator.")
        sys.exit(0)
