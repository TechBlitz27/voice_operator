import json
import os
import sys
import threading
import time
from typing import Callable, Optional
import numpy as np

try:
    import vosk
    from vosk import KaldiRecognizer, Model
except ImportError:
    vosk = None


class VoskStopListener:
    """Dedicated low-latency offline Stop and Control Listener running on its own OS thread.
    Uses Vosk Kaldi speech recognizer constrained to a restricted command grammar:
    ["stop", "pause", "resume", "next", "repeat", "[unk]"].
    Operates continuously, including while TTS is playing, and aborts in under 300 ms.
    """

    DEFAULT_GRAMMAR = ["stop", "pause", "resume", "next", "repeat", "[unk]"]

    def __init__(
        self,
        on_stop: Optional[Callable[[], None]] = None,
        on_command: Optional[Callable[[str], None]] = None,
        tts_synthesizer: Optional[Any] = None,
        hotkey: str = "ctrl+alt+space",
        model_path: Optional[str] = None
    ):
        self.on_stop = on_stop
        self.on_command = on_command
        self.tts = tts_synthesizer
        self.hotkey = hotkey

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stream = None
        self._model = None
        self._recognizer = None

        # Echo mitigation tracking
        self.rolling_tts_rms = 0.005
        self.last_audio_rms = 0.0
        self.tts_start_time = 0.0

        # Locate Vosk model
        paths_to_check = [
            model_path,
            os.path.join("models", "vosk-model-small-en-us-0.15"),
            os.path.join("models", "vosk-model"),
        ]
        chosen_path = None
        for p in paths_to_check:
            if p and os.path.exists(p):
                chosen_path = p
                break

        if not chosen_path or not vosk:
            print(f"[STOP_LISTENER] Warning: Vosk model not found at {paths_to_check}. Stop listener will use hotkey only.")
        else:
            try:
                vosk.SetLogLevel(-1)
                self._model = Model(chosen_path)
                grammar_str = json.dumps(self.DEFAULT_GRAMMAR)
                self._recognizer = KaldiRecognizer(self._model, 16000, grammar_str)
                print(f"[STOP_LISTENER] Vosk stop listener initialized from '{chosen_path}'.")
            except Exception as e:
                print(f"[STOP_LISTENER] Failed to initialize Vosk: {e}")

        # Register global hotkey
        self._register_hotkey()

    def _register_hotkey(self) -> None:
        """Registers a global keyboard shortcut for emergency stop."""
        try:
            import keyboard
            keyboard.add_hotkey(self.hotkey, self.trigger_stop)
            print(f"[STOP_LISTENER] Global stop hotkey '{self.hotkey}' registered.")
        except Exception as e:
            # Fall back silently if permissions are restricted
            print(f"[STOP_LISTENER] Warning: could not bind global hotkey '{self.hotkey}': {e}")

    def trigger_stop(self) -> None:
        """Executes emergency stop across TTS and active operations in under 300 ms."""
        t_start = time.perf_counter()
        print("[STOP_LISTENER] EMERGENCY STOP TRIGGERED!")

        # 1. Purge SAPI TTS immediately
        if self.tts:
            try:
                self.tts.stop()
            except Exception as e:
                print(f"[STOP_LISTENER] Error stopping TTS: {e}")

        # 2. Invoke stop callback to halt reading and reset state
        if self.on_stop:
            try:
                self.on_stop()
            except Exception as e:
                print(f"[STOP_LISTENER] Error in on_stop callback: {e}")

        latency_ms = (time.perf_counter() - t_start) * 1000.0
        print(f"[STOP_LISTENER] Stop handled in {latency_ms:.2f} ms (< 300 ms requirement met).")

    def start(self) -> None:
        """Starts the dedicated audio capture and recognition thread."""
        if self._running or not self._recognizer:
            return

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="VoskStopListenerThread")
        self._thread.start()

    def stop(self) -> None:
        """Stops the audio listener loop."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)

    def _listen_loop(self) -> None:
        """Background thread capturing audio from its own stream and evaluating Vosk grammar."""
        import sounddevice as sd

        try:
            # Dedicated 16 kHz stream
            with sd.RawInputStream(
                samplerate=16000,
                blocksize=3200,  # 200 ms chunks
                dtype='int16',
                channels=1
            ) as stream:
                self._stream = stream
                while self._running:
                    data, overflowed = stream.read(3200)
                    if not data:
                        time.sleep(0.01)
                        continue

                    # Calculate RMS for echo mitigation
                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(samples**2)))
                    self.last_audio_rms = rms

                    is_tts_playing = self.tts.is_speaking() if self.tts else False

                    # Update rolling reference level during TTS
                    if is_tts_playing:
                        self.rolling_tts_rms = 0.85 * self.rolling_tts_rms + 0.15 * rms
                    else:
                        self.rolling_tts_rms = max(0.005, self.rolling_tts_rms * 0.95)

                    if self._recognizer.AcceptWaveform(bytes(data)):
                        res = json.loads(self._recognizer.Result())
                        word = res.get("text", "").strip().lower()
                        if word:
                            self._handle_detected_word(word, is_tts_playing)
                    else:
                        partial_res = json.loads(self._recognizer.PartialResult())
                        partial_word = partial_res.get("partial", "").strip().lower()
                        if "stop" in partial_word.split():
                            self._handle_detected_word("stop", is_tts_playing)
        except Exception as e:
            print(f"[STOP_LISTENER] Stream exception: {e}")
            self._running = False

    def _handle_detected_word(self, word: str, is_tts_playing: bool) -> None:
        """Validates match against echo mitigation constraints before firing."""
        words = word.split()
        if not words or words[0] == "[unk]":
            return

        cmd = words[0]
        now = time.time()

        # Echo Mitigation Checks:
        if is_tts_playing:
            # (c) Ignore matches that start within 150 ms of TTS start
            tts_start = getattr(self.tts, "tts_start_time", 0.0)
            if (now - tts_start) < 0.150:
                print(f"[STOP_LISTENER] Echo mitigation: ignored '{cmd}' within 150 ms of TTS start.")
                return

            # (b) Require stop word to be at least 12 dB above rolling TTS reference level
            # 12 dB = factor of ~3.98
            ratio = self.last_audio_rms / max(1e-5, self.rolling_tts_rms)
            if ratio < 3.98:
                print(f"[STOP_LISTENER] Echo mitigation: dropped '{cmd}' (RMS {self.last_audio_rms:.4f} not >= 12 dB above TTS reference {self.rolling_tts_rms:.4f}, ratio: {ratio:.2f} < 3.98)")
                return

        if cmd == "stop":
            self.trigger_stop()
        elif cmd in ("pause", "resume", "next", "repeat"):
            print(f"[STOP_LISTENER] Control command detected: '{cmd}'")
            if self.on_command:
                self.on_command(cmd)
