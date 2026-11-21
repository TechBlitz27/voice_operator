import math
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from src.adapters.sounddevice_audio import SounddeviceAudio
from src.adapters.mocks.speech_mock import (
    MockAudioSource,
    MockSpeechRecognizer,
    MockSpeechSynthesizer,
    MockVAD,
)
from src.adapters.mocks.llm_mock import MockLLMProvider
from src.adapters.mocks.os_control_mock import MockOSController
from src.core.state_machine.mode_manager import ModeManager
from src.orchestrator import Orchestrator


def test_snr_preserved_within_3db():
    """Verify that audio processing preserves SNR within 3 dB between speech and background."""
    audio = SounddeviceAudio(sample_rate=16000)
    audio.device_sample_rate = 16000
    audio.device_dtype = "float32"
    audio.device_channels = 1
    audio._stream = MagicMock()
    audio.noise_floor = 50.0

    sr = 16000
    np.random.seed(42)

    # 0.5s of speech (tone + noise) and 0.5s of silence/background noise
    n_half = sr // 2
    t_half = np.arange(n_half) / sr
    speech_signal = 0.3 * np.sin(2 * np.pi * 300 * t_half)
    speech_noise = 0.015 * np.random.randn(n_half)
    speech_part = (speech_signal + speech_noise).astype(np.float32)

    silence_part = (0.015 * np.random.randn(n_half)).astype(np.float32)

    input_speech_rms = float(np.sqrt(np.mean(speech_part ** 2)))
    input_noise_rms = float(np.sqrt(np.mean(silence_part ** 2)))
    snr_in_db = 20.0 * np.log10(input_speech_rms / max(input_noise_rms, 1e-9))

    # Feed speech part in 512-sample blocks
    out_speech_blocks = []
    for i in range(0, n_half, 512):
        block = speech_part[i : i + 512]
        if len(block) < 512:
            break
        audio._audio_callback(block.reshape(-1, 1), None, None, None)
        while not audio._audio_queue.empty():
            out_speech_blocks.append(audio._audio_queue.get_nowait())

    # Feed silence part in 512-sample blocks
    out_silence_blocks = []
    for i in range(0, n_half, 512):
        block = silence_part[i : i + 512]
        if len(block) < 512:
            break
        audio._audio_callback(block.reshape(-1, 1), None, None, None)
        while not audio._audio_queue.empty():
            out_silence_blocks.append(audio._audio_queue.get_nowait())

    out_speech_samples = np.frombuffer(b"".join(out_speech_blocks), dtype=np.int16).astype(np.float64)
    out_silence_samples = np.frombuffer(b"".join(out_silence_blocks), dtype=np.int16).astype(np.float64)

    out_speech_rms = float(np.sqrt(np.mean(out_speech_samples ** 2)))
    out_noise_rms = float(np.sqrt(np.mean(out_silence_samples ** 2)))
    snr_out_db = 20.0 * np.log10(out_speech_rms / max(out_noise_rms, 1e-9))

    snr_diff = abs(snr_out_db - snr_in_db)
    assert snr_diff <= 3.0, (
        f"SNR degraded by AGC/processing: SNR in={snr_in_db:.2f} dB, "
        f"SNR out={snr_out_db:.2f} dB, diff={snr_diff:.2f} dB (> 3.0 dB)"
    )


@pytest.mark.asyncio
async def test_persistent_stream_not_stopped_per_utterance():
    """Audio stream must remain open across utterances (no stop_stream per utterance)."""
    class PersistentTestAudioSource:
        def __init__(self):
            self.stop_count = 0
            self.start_count = 0
            self._exhausted = False

        def start_stream(self, calibrate=False):
            self.start_count += 1

        def stop_stream(self):
            self.stop_count += 1

        def read_chunk(self):
            return b""

        def is_exhausted(self):
            return True

    source = PersistentTestAudioSource()
    vad = MockVAD()
    recognizer = MockSpeechRecognizer()
    recognizer._initialized = True
    recognizer.queue_transcription("test persistence")
    synthesizer = MockSpeechSynthesizer()
    mode_manager = ModeManager(MockLLMProvider(), MockOSController(), synthesizer)
    orch = Orchestrator(source, vad, recognizer, synthesizer, mode_manager)

    try:
        await orch.run_single_step()
    except EOFError:
        pass

    assert source.stop_count == 0, "Audio stream was stopped per utterance instead of persisting."


@pytest.mark.asyncio
async def test_single_vad_hysteresis_ends_speech_without_second_counter():
    """Orchestrator must rely on VAD's speech state without a redundant 16/32 silence frame counter."""
    class MockHysteresisVAD:
        def __init__(self):
            # 11 frames of True (11 * 32ms = 352ms > 300ms min), then False
            self.frames = [True] * 11 + [False]
            self.idx = 0

        def reset_state(self):
            self.idx = 0

        def is_speech(self, chunk):
            if self.idx < len(self.frames):
                res = self.frames[self.idx]
                self.idx += 1
                return res
            return False

    class ChunkSource:
        def __init__(self, items):
            self.items = list(items)
            self.idx = 0
        def start_stream(self, calibrate=False):
            pass
        def stop_stream(self):
            pass
        def read_chunk(self):
            if self.idx < len(self.items):
                c = self.items[self.idx]
                self.idx += 1
                return c
            return b""
        def is_exhausted(self):
            return self.idx >= len(self.items)

    chunks = [b"\x01\x00" * 512 for _ in range(16)]
    source = ChunkSource(chunks)
    vad = MockHysteresisVAD()
    recognizer = MockSpeechRecognizer()
    transcribed_buffers = []
    recognizer.transcribe = lambda buf: transcribed_buffers.append(buf) or "done"
    synthesizer = MockSpeechSynthesizer()
    mode_manager = ModeManager(MockLLMProvider(), MockOSController(), synthesizer)
    orch = Orchestrator(source, vad, recognizer, synthesizer, mode_manager)

    await orch.run_single_step()

    # Once VAD reports False after speech, recording stops immediately without waiting for 16 extra frames
    assert len(transcribed_buffers) == 1
    # 11 frames of speech + 1 frame when VAD went False, NOT 16 extra chunks
    assert 11 * 512 * 2 <= len(transcribed_buffers[0]) <= 13 * 512 * 2


@pytest.mark.asyncio
async def test_audio_clock_duration_used_in_logging(tmp_path):
    """Session log duration must match audio clock (sample count / 16000), not wall-clock time."""
    import json
    log_file = tmp_path / "session.jsonl"

    class SampleSource:
        def __init__(self):
            # 10 chunks of 512 samples = 5120 samples = exactly 0.320 s of audio
            self.chunks = [b"\x01\x00" * 512 for _ in range(10)]
            self.idx = 0

        def start_stream(self, calibrate=False):
            pass
        def stop_stream(self):
            pass
        def read_chunk(self):
            if self.idx < len(self.chunks):
                c = self.chunks[self.idx]
                self.idx += 1
                return c
            return b""
        def is_exhausted(self):
            return self.idx >= len(self.chunks)

    class TimedVAD:
        def __init__(self):
            self.step = 0
        def reset_state(self):
            self.step = 0
        def is_speech(self, chunk):
            self.step += 1
            # Active for first 9 chunks, False on chunk 10
            return self.step <= 9

    source = SampleSource()
    vad = TimedVAD()
    recognizer = MockSpeechRecognizer()
    recognizer.transcribe = lambda b: "test audio clock"
    synthesizer = MockSpeechSynthesizer()
    mode_manager = ModeManager(MockLLMProvider(), MockOSController(), synthesizer)
    orch = Orchestrator(source, vad, recognizer, synthesizer, mode_manager, session_log_path=str(log_file))

    await orch.run_single_step()

    assert log_file.exists()
    with open(log_file, "r") as f:
        line = f.readline()
        entry = json.loads(line)

    expected_audio_clock_sec = round(len(source.chunks) * 512 / 16000.0, 3)
    # The logged duration must match audio-clock duration exactly
    assert abs(entry["duration"] - expected_audio_clock_sec) < 0.05

