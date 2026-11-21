import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from src.adapters.sounddevice_audio import SounddeviceAudio

def test_audio_source_stream_lifecycle():
    """Verifies that sounddevice start, read, and stop stream sequence runs successfully."""
    # Mock sounddevice InputStream
    mock_stream = MagicMock()
    
    with patch("sounddevice.InputStream", return_value=mock_stream) as mock_input_class:
        audio = SounddeviceAudio()
        
        # 1. Start stream
        audio.start_stream()
        mock_input_class.assert_called_once()
        mock_stream.start.assert_called_once()
        
        # 2. Simulate chunk retrieval
        audio.device_sample_rate = 16000
        audio.device_dtype = "int16"
        dummy_data = np.zeros((512, 1), dtype=np.int16)
        audio._audio_callback(dummy_data, None, None, None)
        chunk = audio.read_chunk()
        assert len(chunk) == 1024
        
        # 3. Stop stream
        audio.stop_stream()
        mock_stream.stop.assert_called_once()
        mock_stream.close.assert_called_once()


def test_audio_source_read_without_start():
    """Verifies that reading from a stream before calling start raises RuntimeError."""
    audio = SounddeviceAudio()
    with pytest.raises(RuntimeError):
        audio.read_chunk()


def test_audio_source_sample_rate_downsampling_and_float32_conversion():
    """Hostile test: Verifies hardware 48kHz float32 audio callback downsamples to 16kHz int16 correctly."""
    audio = SounddeviceAudio(sample_rate=16000)
    audio.device_sample_rate = 48000
    audio.device_dtype = 'float32'
    audio._stream = MagicMock()  # Mock active stream handle
    
    # 1536 samples at 48kHz float32 -> downsampled by 3 -> 512 samples at 16kHz int16 (1024 bytes)
    dummy_48k_float = np.linspace(-1.0, 1.0, 1536, dtype=np.float32).reshape(-1, 1)
    audio._audio_callback(dummy_48k_float, None, None, None)
    
    chunk = audio.read_chunk()
    assert len(chunk) == 1024  # 512 int16 samples = 1024 bytes
    
    # Convert back to numpy array to verify data range
    int16_samples = np.frombuffer(chunk, dtype=np.int16)
    assert len(int16_samples) == 512
    assert int16_samples.min() >= -32768
    assert int16_samples.max() <= 32767


def test_audio_source_no_devices_available():
    """Hostile test: default-device failures report how to select a microphone."""
    with patch("sounddevice.InputStream", side_effect=Exception("PortAudio device error")):
        audio = SounddeviceAudio()
        audio._fallback_input_devices = lambda: []
        with pytest.raises(RuntimeError, match="list-audio-devices"):
            audio.start_stream()


def test_audio_source_double_stop():
    """Verifies that calling stop multiple times does not raise exceptions."""
    mock_stream = MagicMock()
    with patch("sounddevice.InputStream", return_value=mock_stream):
        audio = SounddeviceAudio()
        audio.start_stream()
        audio.stop_stream()
        # Second stop should be ignored safely
        audio.stop_stream()


def test_audio_source_uses_requested_input_device():
    """An explicit Windows microphone index is forwarded to sounddevice."""
    mock_stream = MagicMock()
    with patch("sounddevice.query_devices", return_value={"default_samplerate": 48000}), \
         patch("sounddevice.InputStream", return_value=mock_stream) as input_stream:
        audio = SounddeviceAudio(device=4)
        audio.start_stream()

    assert input_stream.call_args.kwargs["device"] == 4
    assert input_stream.call_args.kwargs["samplerate"] == 48000


def test_audio_source_discards_oldest_frame_when_queue_is_full():
    audio = SounddeviceAudio()
    audio._audio_queue = __import__("queue").Queue(maxsize=1)
    audio.device_sample_rate = 16000
    audio.device_dtype = "int16"
    audio._audio_callback(np.full((2, 1), 1, dtype=np.int16), None, None, None)
    audio._audio_callback(np.full((2, 1), 2, dtype=np.int16), None, None, None)
    assert np.frombuffer(audio._audio_queue.get_nowait(), dtype=np.int16).tolist() == [2, 2]


def test_recorded_audio_source(tmp_path):
    """Verifies that RecordedAudioSource accurately loads WAV files and emits 32ms streaming chunks."""
    import wave
    from src.adapters.recorded_audio import RecordedAudioSource
    
    # Create synthetic test WAV file: 16kHz mono 16-bit PCM, 1024 samples (2 frames of 512 samples)
    wav_file = tmp_path / "test.wav"
    samples = np.linspace(-1000, 1000, 1024, dtype=np.int16)
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(samples.tobytes())
        
    source = RecordedAudioSource(str(wav_file), block_size=512)
    assert not source.is_exhausted()
    
    # Read chunk 1
    c1 = source.read_chunk()
    assert len(c1) == 1024  # 512 * 2 bytes
    assert not source.is_exhausted()
    
    # Read chunk 2
    c2 = source.read_chunk()
    assert len(c2) == 1024
    assert source.is_exhausted()
    
    # Read past end
    c3 = source.read_chunk()
    assert c3 == b""
    assert source.is_exhausted()


@pytest.mark.asyncio
async def test_orchestrator_eof_handling_during_idle_and_dictation(tmp_path):
    """Task 7 & 10: Verifies Orchestrator cleanly detects RecordedAudio EOF without hanging."""
    import wave
    from src.adapters.recorded_audio import RecordedAudioSource
    from src.adapters.mocks.speech_mock import MockVAD, MockSpeechSynthesizer
    from src.adapters.mocks.llm_mock import MockLLMProvider
    from src.adapters.mocks.os_control_mock import MockOSController
    from src.core.state_machine.mode_manager import ModeManager
    from src.orchestrator import Orchestrator
    
    # Create empty 16kHz WAV file (0 frames)
    wav_file = tmp_path / "empty.wav"
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"")
        
    source = RecordedAudioSource(str(wav_file), block_size=512)
    vad = MockVAD()
    tts = MockSpeechSynthesizer()
    mm = ModeManager(MockLLMProvider(), MockOSController(), tts)
    orch = Orchestrator(source, vad, None, tts, mm)
    
    # 1. EOF while waiting for speech in Command Mode raises EOFError
    with pytest.raises(EOFError):
        await orch.run_single_step()
        
    # 2. EOF while in Dictation Mode also raises EOFError cleanly
    mm.set_mode("dictation")
    source2 = RecordedAudioSource(str(wav_file), block_size=512)
    orch2 = Orchestrator(source2, vad, None, tts, mm)
    with pytest.raises(EOFError):
        await orch2.run_single_step()


def test_resampling_anti_aliasing_synthetic_tone():
    """Unit test: a 1 kHz plus 7 kHz synthetic tone at 48 kHz must not show alias energy in the 16 kHz output."""
    audio = SounddeviceAudio(sample_rate=16000)
    audio.device_sample_rate = 48000
    audio.device_dtype = "float32"
    audio.device_channels = 1
    audio._stream = MagicMock()

    # Generate 1.0 second of 1 kHz + 7 kHz tone at 48 kHz
    sr = 48000
    t = np.arange(sr) / sr
    sig_48k = (np.sin(2 * np.pi * 1000 * t) + np.sin(2 * np.pi * 7000 * t)).astype(np.float32)

    # Process through SounddeviceAudio callback
    audio._audio_callback(sig_48k.reshape(-1, 1), None, None, None)

    # Collect resampled 16 kHz audio from the queue
    chunks = []
    while not audio._audio_queue.empty():
        chunks.append(audio._audio_queue.get_nowait())
    resampled_bytes = b"".join(chunks)
    resampled_samples = np.frombuffer(resampled_bytes, dtype=np.int16).astype(np.float32)

    # Compute FFT of 16 kHz resampled output
    fft_mag = np.abs(np.fft.rfft(resampled_samples))
    freqs = np.fft.rfftfreq(len(resampled_samples), 1.0 / 16000.0)

    # Verify 1 kHz and 7 kHz peaks are present
    peak_1k = np.max(fft_mag[np.abs(freqs - 1000) < 50])
    peak_7k = np.max(fft_mag[np.abs(freqs - 7000) < 50])
    assert peak_1k > 1000.0, "Expected prominent 1 kHz tone in 16 kHz output"
    assert peak_7k > 1000.0, "Expected prominent 7 kHz tone in 16 kHz output"

    # Verify no alias / spurious energy across the spectrum (> 60 dB down)
    mask_noise = (np.abs(freqs - 1000) > 100) & (np.abs(freqs - 7000) > 100)
    max_alias_energy = np.max(fft_mag[mask_noise])
    spurious_ratio = max_alias_energy / peak_1k

    assert spurious_ratio < 1e-3, (
        f"Alias or spurious energy detected in 16 kHz output: ratio={spurious_ratio:.6f} "
        f"(max alias={max_alias_energy:.2f}, fundamental={peak_1k:.2f})"
    )


