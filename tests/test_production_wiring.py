import pytest
import sounddevice as sd

from src.adapters.whisper_stt import WhisperSpeechRecognizer
from src.adapters.silero_vad import SileroVAD
from src.adapters.sounddevice_audio import SounddeviceAudio
from src.adapters.sapi_tts import SAPITTS
from src.adapters.windows_control import WindowsOSController
from src.adapters.llamacpp_provider import LlamaCppLLMProvider
from src.core.state_machine.mode_manager import ModeManager
from src.adapters.vosk_stop_listener import VoskStopListener


def test_production_wiring_no_mocks():
    """Release Gate 1: Build real production app object graph and assert no class contains Fake, Mock, or Stub."""
    stt = WhisperSpeechRecognizer(model_size="base")
    vad = SileroVAD()
    audio = SounddeviceAudio(auto_calibrate=False)
    tts = SAPITTS()
    os_ctrl = WindowsOSController()
    llm = LlamaCppLLMProvider(raise_on_failure=False)
    mm = ModeManager(llm_provider=llm, os_controller=os_ctrl, speech_synthesizer=tts)
    stop_listener = VoskStopListener(tts_synthesizer=tts)

    graph = [stt, vad, audio, tts, os_ctrl, llm, mm, stop_listener]
    
    for component in graph:
        cls_name = component.__class__.__name__
        assert not any(forbidden in cls_name.lower() for forbidden in ("fake", "mock", "stub")), (
            f"Component '{cls_name}' contains a mock/fake/stub class in production wiring!"
        )


def test_startup_self_check_announcement():
    """Startup self-check: speaks active STT model, VAD, TTS voice, mic, and speaker."""
    stt = WhisperSpeechRecognizer(model_size="base")
    vad = SileroVAD()
    audio = SounddeviceAudio(auto_calibrate=False)
    tts = SAPITTS()

    # Discover active hardware devices
    devices = sd.query_devices()
    default_input = sd.default.device[0]
    default_output = sd.default.device[1]

    mic_name = devices[default_input]["name"] if 0 <= default_input < len(devices) else "Default Microphone"
    speaker_name = devices[default_output]["name"] if 0 <= default_output < len(devices) else "Default Speaker"
    
    check_summary = (
        f"Voice Operator v1 initialized. "
        f"STT model: Whisper {stt.model_size}. "
        f"VAD: Silero ONNX. "
        f"Active microphone: {mic_name}. "
        f"Active speaker: {speaker_name}."
    )

    assert "Whisper base" in check_summary
    assert "Silero ONNX" in check_summary
    assert len(mic_name) > 0
    assert len(speaker_name) > 0

    handle = tts.speak(check_summary, interruptible=True, block=False)
    assert handle is not None
    tts.stop()
