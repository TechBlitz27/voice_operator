import pytest
import time
import sounddevice as sd
from src.adapters.sounddevice_audio import SounddeviceAudio

@pytest.mark.integration
def test_real_audio_microphone_recording():
    """Verifies that sounddevice can connect to and query local recording devices without crashing."""
    devices = sd.query_devices()
    if len(devices) == 0:
        pytest.skip("No audio recording devices found on this system.")
        
    audio = SounddeviceAudio()
    try:
        # Start recording stream
        audio.start_stream()
        
        # Capture for 0.5s
        time.sleep(0.5)
        chunk = audio.read_chunk()
        
        # Audio block should contain bytes
        assert isinstance(chunk, bytes)
        
    finally:
        audio.stop_stream()
