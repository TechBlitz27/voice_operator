import os
import sys
import threading
from typing import Optional, Union

import numpy as np

from src.core.interfaces.audio import VoiceActivityDetector


def _speak_vad_error(text: str) -> None:
    """Announce missing model error using native SAPI in a non-blocking thread."""
    def _worker():
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            voice.Speak(text)
            pythoncom.CoUninitialize()
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


class SileroVAD(VoiceActivityDetector):
    """Production Voice Activity Detector using Silero VAD ONNX with:
    - 64-sample context prefix + 512-sample frame feeding
    - LSTM state retention across frames
    - Hysteresis: starts on >= 0.5 for 3 consecutive frames; ends after 500 ms below 0.35
    - Speech duration constraints: minimum 300 ms, capped at 15 s
    - Loud failure at startup if model weights are missing (no silent fallback).
    """

    FRAME_SIZE = 512        # 32 ms at 16 kHz
    CONTEXT_SIZE = 64      # 4 ms context prefix
    TOTAL_INPUT_SIZE = 576  # 512 + 64

    # Hysteresis parameters
    START_PROB = 0.50
    START_CONSECUTIVE_FRAMES = 3
    END_PROB = 0.35
    END_SILENCE_MS = 500.0   # 500 ms below END_PROB terminates speech
    MIN_SPEECH_MS = 300.0    # 300 ms minimum speech length
    MAX_SPEECH_SEC = 15.0    # 15 s hard cap

    def __init__(self, sample_rate: int = 16000, model_path: Optional[str] = None):
        self.sample_rate = sample_rate
        self.frame_duration_sec = self.FRAME_SIZE / self.sample_rate  # 0.032 s

        self._session = None
        self._initialized = False

        # Neural recurrent state
        self._context = np.zeros(self.CONTEXT_SIZE, dtype=np.float32)
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._v4_state = np.zeros((2, 1, 128), dtype=np.float32)
        self._model_input_type = "hc"  # "hc" for v5/v6 or "state" for v4

        # Hysteresis state tracking
        self.in_speech: bool = False
        self._consecutive_high_frames: int = 0
        self._silence_duration_ms: float = 0.0
        self._speech_duration_ms: float = 0.0
        self.last_prob: float = 0.0
        self.is_valid_speech: bool = False

        # Load Silero ONNX model
        self._load_model(model_path)

    def _load_model(self, explicit_path: Optional[str] = None) -> None:
        """Loads Silero ONNX runtime session or fails loudly with spoken and logged error."""
        candidate_paths = []
        if explicit_path:
            candidate_paths.append(explicit_path)
        candidate_paths.extend([
            os.path.join("models", "silero_vad.onnx"),
            os.path.join(".venv", "Lib", "site-packages", "faster_whisper", "assets", "silero_vad_v6.onnx"),
        ])

        found_path = None
        for p in candidate_paths:
            if os.path.exists(p):
                found_path = p
                break

        if not found_path:
            err_msg = (
                "[VAD] CRITICAL ERROR: Silero VAD ONNX model is missing at 'models/silero_vad.onnx'. "
                "Voice Operator v1 requires the neural Silero VAD model to operate. Cannot start."
            )
            print(err_msg, file=sys.stderr)
            _speak_vad_error("Error: Silero voice activity detector model is missing.")
            raise FileNotFoundError(
                "Silero VAD ONNX model is missing at 'models/silero_vad.onnx'. "
                "Install the local ONNX weights before starting production mode."
            )

        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 1
            self._session = ort.InferenceSession(found_path, sess_options=opts)
            self._initialized = True

            # Determine input schema (v5/v6 vs v4)
            input_names = [inp.name for inp in self._session.get_inputs()]
            if "h" in input_names and "c" in input_names:
                self._model_input_type = "hc"
            else:
                self._model_input_type = "state"

            print(f"[VAD] Silero VAD loaded successfully from '{found_path}' (schema: {self._model_input_type}).")
        except Exception as e:
            err_msg = f"[VAD] CRITICAL ERROR: Failed to load Silero VAD ONNX session: {e}"
            print(err_msg, file=sys.stderr)
            _speak_vad_error("Error: Failed to initialize Silero voice activity detector.")
            raise RuntimeError(err_msg) from e

    def reset_state(self) -> None:
        """Resets recurrent LSTM state, 64-sample context prefix, and hysteresis counters."""
        self._context = np.zeros(self.CONTEXT_SIZE, dtype=np.float32)
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._v4_state = np.zeros((2, 1, 128), dtype=np.float32)

        self.in_speech = False
        self._consecutive_high_frames = 0
        self._silence_duration_ms = 0.0
        self._speech_duration_ms = 0.0
        self.last_prob = 0.0
        self.is_valid_speech = False

    def get_speech_prob(self, audio_chunk: Union[bytes, np.ndarray]) -> float:
        """Run Silero VAD inference on a 512-sample frame with the 64-sample context prefix.
        Maintains recurrent LSTM hidden state across frames.
        """
        if not audio_chunk:
            return 0.0

        if isinstance(audio_chunk, bytes):
            audio_data = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        else:
            audio_data = np.asarray(audio_chunk, dtype=np.float32)
            if np.max(np.abs(audio_data)) > 1.0:
                audio_data = audio_data / 32768.0

        # Ensure frame length is 512 samples
        if len(audio_data) < self.FRAME_SIZE:
            audio_data = np.pad(audio_data, (0, self.FRAME_SIZE - len(audio_data)))
        elif len(audio_data) > self.FRAME_SIZE:
            audio_data = audio_data[:self.FRAME_SIZE]

        # Feed 512-sample frame with 64-sample context prefix -> 576 samples
        input_576 = np.concatenate([self._context, audio_data]).astype(np.float32)
        self._context = audio_data[-self.CONTEXT_SIZE:].copy()

        prob = 0.0
        try:
            if self._model_input_type == "hc":
                inputs = {
                    "input": input_576[np.newaxis, :],
                    "h": self._h,
                    "c": self._c,
                }
                out = self._session.run(None, inputs)
                prob = float(out[0][0]) if out and len(out) > 0 else 0.0
                if len(out) > 2:
                    self._h = out[1]
                    self._c = out[2]
            else:
                inputs = {
                    "input": input_576[np.newaxis, :],
                    "state": self._v4_state,
                    "sr": np.array(self.sample_rate, dtype=np.int64),
                }
                out = self._session.run(None, inputs)
                prob = float(out[0][0][0]) if out and len(out) > 0 else 0.0
                if len(out) > 1:
                    self._v4_state = out[1]
        except Exception as e:
            print(f"[VAD] ONNX inference error: {e}", file=sys.stderr)
            prob = 0.0

        self.last_prob = prob
        return prob

    def is_speech(self, audio_chunk: Union[bytes, np.ndarray]) -> bool:
        """Evaluates whether the frame constitutes speech using dual-threshold hysteresis:
        - Starts speech at probability >= 0.50 for 3 consecutive frames.
        - Ends speech after 500 ms below 0.35.
        - Enforces minimum speech length of 300 ms and caps at 15.0 s.
        """
        prob = self.get_speech_prob(audio_chunk)
        frame_ms = self.frame_duration_sec * 1000.0  # 32 ms

        if not self.in_speech:
            if prob >= self.START_PROB:
                self._consecutive_high_frames += 1
                if self._consecutive_high_frames >= self.START_CONSECUTIVE_FRAMES:
                    # Speech start triggered
                    self.in_speech = True
                    self._speech_duration_ms = self._consecutive_high_frames * frame_ms
                    self._silence_duration_ms = 0.0
            else:
                self._consecutive_high_frames = 0
        else:
            # Currently in speech
            self._speech_duration_ms += frame_ms

            # Check 15 s hard cap
            if (self._speech_duration_ms / 1000.0) >= self.MAX_SPEECH_SEC:
                self.in_speech = False
                self._consecutive_high_frames = 0
                self.is_valid_speech = self._speech_duration_ms >= self.MIN_SPEECH_MS
                return False

            if prob < self.END_PROB:
                self._silence_duration_ms += frame_ms
                if self._silence_duration_ms >= self.END_SILENCE_MS:
                    # Speech end triggered
                    self.in_speech = False
                    self._consecutive_high_frames = 0
                    self.is_valid_speech = self._speech_duration_ms >= self.MIN_SPEECH_MS
                    return False
            else:
                self._silence_duration_ms = 0.0

            # Update validity flag during active speech
            self.is_valid_speech = self._speech_duration_ms >= self.MIN_SPEECH_MS

        return self.in_speech
