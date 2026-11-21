import pytest
import time
from src.adapters.sapi_tts import SAPITTS

@pytest.mark.integration
def test_real_sapi_tts_device():
    """Natively speaks a phrase using SAPI5 on Windows and checks status."""
    tts = SAPITTS()
    
    tts.speak("Real SAPI TTS speaking test.")
    time.sleep(0.5)
    
    assert tts.is_speaking() is True
    
    tts.stop()
    assert tts.is_speaking() is False
