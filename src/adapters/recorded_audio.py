import os
import wave
from typing import List, Optional
import numpy as np
from src.core.interfaces.audio import AudioSource

class RecordedAudioSource(AudioSource):
    """Production AudioSource that feeds pre-recorded audio in streaming chunks.
    
    Maintains a persistent playback cursor across utterance cycles so an entire
    recorded test session flows through real VAD, STT, LLM, and OS execution.
    """

    def __init__(self, audio_path: str, block_size: int = 512, sample_rate: int = 16000):
        self.audio_path = audio_path
        self.block_size = block_size
        self.sample_rate = sample_rate
        self._chunks: List[bytes] = []
        self._index: int = 0
        self._is_loaded: bool = False
        self._load_audio()

    def _load_audio(self) -> None:
        if not os.path.exists(self.audio_path):
            raise FileNotFoundError(f"Recorded audio file not found: {self.audio_path}")

        # Check if file is a WAV
        if self.audio_path.lower().endswith(".wav"):
            with wave.open(self.audio_path, "rb") as wf:
                channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                nframes = wf.getnframes()
                raw_data = wf.readframes(nframes)
                
            # If standard 16kHz mono 16-bit
            if channels == 1 and sampwidth == 2 and framerate == self.sample_rate:
                raw_bytes = raw_data
            else:
                # Convert format with numpy
                dtype = np.int16 if sampwidth == 2 else (np.uint8 if sampwidth == 1 else np.int32)
                data = np.frombuffer(raw_data, dtype=dtype)
                if channels > 1:
                    data = data.reshape(-1, channels)[:, 0]
                if framerate != self.sample_rate:
                    out_len = max(1, round(len(data) * self.sample_rate / framerate))
                    data = np.interp(np.linspace(0, len(data), out_len, endpoint=False),
                                     np.arange(len(data)), data)
                raw_bytes = np.asarray(data, dtype=np.int16).tobytes()
        else:
            # For MP3 or other formats, try soundfile or fallback
            try:
                import soundfile as sf
                data, samplerate = sf.read(self.audio_path, dtype="float32")
                if data.ndim > 1:
                    data = data[:, 0]
                if samplerate != self.sample_rate:
                    out_len = max(1, round(len(data) * self.sample_rate / samplerate))
                    data = np.interp(np.linspace(0, len(data), out_len, endpoint=False),
                                     np.arange(len(data)), data)
                raw_bytes = (data * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()
            except Exception as e:
                raise ValueError(
                    f"Unsupported audio format for '{self.audio_path}': {e}. "
                    "Please provide a 16kHz mono 16-bit PCM WAV file."
                ) from e

        chunk_bytes = self.block_size * 2  # 512 samples * 2 bytes per sample = 1024 bytes
        self._chunks = [
            raw_bytes[i:i + chunk_bytes]
            for i in range(0, len(raw_bytes), chunk_bytes)
        ]
        self._index = 0
        self._is_loaded = True
        duration = (len(raw_bytes) / 2) / self.sample_rate
        print(f"[RecordedAudio] Loaded '{self.audio_path}': {len(self._chunks)} chunks (~{duration:.2f}s).")

    def start_stream(self) -> None:
        """Starts or continues audio stream playback without resetting the cursor."""
        pass

    def read_chunk(self) -> bytes:
        """Returns the next 32ms audio chunk from the recorded stream."""
        if self._index >= len(self._chunks):
            return b""
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk

    def is_exhausted(self) -> bool:
        """Returns True if the entire recorded audio has been played."""
        return self._index >= len(self._chunks)

    def stop_stream(self) -> None:
        """Stops the audio stream while preserving the current playback cursor."""
        pass
