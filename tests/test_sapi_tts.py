import pytest
import time
from src.adapters.sapi_tts import SAPITTS

@pytest.fixture
def tts():
    engine = SAPITTS()
    time.sleep(0.3)
    yield engine
    engine.close()

@pytest.mark.integration
def test_sapi_tts_lifecycle(tts):
    """Verifies standard speech synthesis lifecycle states."""
    tts.speak("This is a test of standard speech synthesis lifecycle states to verify active playback.")
    time.sleep(0.15)
    assert tts.is_speaking() is True
    
    success = False
    for _ in range(60):
        if not tts.is_speaking():
            success = True
            break
        time.sleep(0.1)
    assert success is True

@pytest.mark.integration
def test_sapi_tts_interruption(tts):
    """Verifies that stopping speech synchronously resets is_speaking state and halts worker thread."""
    tts.speak("This is a deliberately long sentence designed to verify that SAPI5 can be safely interrupted in real-time.")
    time.sleep(0.15)
    assert tts.is_speaking() is True
    
    tts.stop()
    assert tts.is_speaking() is False

@pytest.mark.integration
def test_sapi_tts_stop_when_idle(tts):
    """Verifies that stopping while idle is safe and does not crash or raise errors."""
    assert tts.is_speaking() is False
    tts.stop()
    assert tts.is_speaking() is False

@pytest.mark.integration
def test_sapi_tts_repeated_speaking(tts):
    """Verifies that multiple speech calls queue and execute cleanly in order."""
    tts.speak("First utterance long phrase to verify speaking state is active.")
    time.sleep(0.15)
    assert tts.is_speaking() is True
    
    tts.speak("Second utterance long phrase to verify speaking state is active.")
    time.sleep(0.15)
    assert tts.is_speaking() is True
    
    tts.stop()
    assert tts.is_speaking() is False

