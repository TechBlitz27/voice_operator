import asyncio
import sys
import time
from typing import Any, Dict, Optional
from src.core.interfaces.audio import AudioSource, VoiceActivityDetector
from src.core.interfaces.speech import SpeechRecognizer, SpeechSynthesizer
from src.core.state_machine.mode_manager import ModeManager

class Orchestrator:
    """The Composition Root that coordinates the voice pipeline and state machine."""

    def __init__(
        self,
        audio_source: AudioSource,
        vad: VoiceActivityDetector,
        speech_recognizer: SpeechRecognizer,
        speech_synthesizer: SpeechSynthesizer,
        mode_manager: ModeManager,
        keep_audio: bool = False,
        session_log_path: str = "logs/session.jsonl",
        stop_listener: Optional[Any] = None,
    ):
        self.audio_source = audio_source
        self.vad = vad
        self.speech_recognizer = speech_recognizer
        self.speech_synthesizer = speech_synthesizer
        self.mode_manager = mode_manager
        self.keep_audio = keep_audio
        self.session_log_path = session_log_path
        self.stop_listener = stop_listener

    async def run_single_step(self, mock_audio_data: bytes = b"") -> Dict[str, Any]:
        """Runs a single step of the audio command pipeline.
        
        This encapsulates: Audio capture -> VAD -> STT -> Routing -> Execution.
        """
        # 1. Capture speech transcription
        from src.adapters.mocks.speech_mock import MockAudioSource
        is_mock = isinstance(self.audio_source, MockAudioSource)

        captured_audio_bytes = b""
        max_vad_prob = 0.0

        if mock_audio_data or is_mock:
            captured_audio_bytes = mock_audio_data
            max_vad_prob = 1.0 if mock_audio_data else 0.0
            transcription = self.speech_recognizer.transcribe(mock_audio_data)
        else:
            # Live production mode: wait for speech via VAD loop
            # If the speech recognizer has failed initialization (e.g. package not installed),
            # fall back directly to console input without listening to empty microphone.
            if hasattr(self.speech_recognizer, "_initialized") and not self.speech_recognizer._initialized:
                transcription = self.speech_recognizer.transcribe(b"")
            else:
                import collections
                print("[ORCHESTRATOR] Listening... Speak now.")
                if hasattr(self.vad, "reset_state"):
                    self.vad.reset_state()

                audio_buffer = bytearray()
                preroll_buffer = collections.deque(maxlen=16)

                # Maintain persistent stream: open only if not already active
                if hasattr(self.audio_source, "_stream"):
                    if not self.audio_source._stream or not getattr(self.audio_source._stream, "active", False):
                        self.audio_source.start_stream(calibrate=False)
                if hasattr(self.audio_source, "flush"):
                    self.audio_source.flush()

                speech_started = False
                max_record_samples = int(15.0 * 16000)  # Capped at 15 s per requirement

                listen_start = time.time()
                timeout = 10.0  # Listen up to 10 seconds for user speech to start

                while True:
                    # Speaker mode: Duck TTS volume while listening rather than discarding frames
                    if hasattr(self.speech_synthesizer, "is_speaking") and self.speech_synthesizer.is_speaking():
                        if hasattr(self.speech_synthesizer, "set_volume"):
                            try:
                                self.speech_synthesizer.set_volume(20)
                            except Exception:
                                pass
                    elif hasattr(self.speech_synthesizer, "set_volume"):
                        try:
                            self.speech_synthesizer.set_volume(100)
                        except Exception:
                            pass

                    chunk = self.audio_source.read_chunk()
                    if not chunk:
                        if hasattr(self.audio_source, "is_exhausted") and self.audio_source.is_exhausted():
                            if speech_started:
                                print("[ORCHESTRATOR] End of recorded audio reached. Finalizing recording.")
                                break
                            else:
                                print("[RecordedAudio] End of recording reached.")
                                print("[ORCHESTRATOR] Recorded audio test completed.")
                                raise EOFError("Recorded audio input stream reached end of file.")
                        await asyncio.sleep(0.01)
                        continue

                    is_speech = self.vad.is_speech(chunk)

                    if is_speech:
                        if not speech_started:
                            print("[ORCHESTRATOR] Speech detected. Recording...")
                            speech_started = True
                            # Attach all pre-roll audio so initial onset frames are never dropped
                            for pre_chunk in preroll_buffer:
                                audio_buffer.extend(pre_chunk)
                            preroll_buffer.clear()
                        audio_buffer.extend(chunk)
                        # Audio-clock duration check (samples recorded)
                        if (len(audio_buffer) // 2) >= max_record_samples:
                            print("[ORCHESTRATOR] Maximum utterance duration reached. Stop recording.")
                            break
                    else:
                        if speech_started:
                            # Speech end detected by VAD hysteresis (single VAD hysteresis, no second silence counter)
                            audio_buffer.extend(chunk)
                            recorded_dur = (len(audio_buffer) // 2) / 16000.0
                            # Enforce 300 ms minimum speech length
                            if recorded_dur < 0.30:
                                print(f"[ORCHESTRATOR] Discarding short audio burst ({recorded_dur*1000:.0f}ms < 300ms min).")
                                speech_started = False
                                audio_buffer.clear()
                                preroll_buffer.clear()
                                continue
                            print("[ORCHESTRATOR] Speech end detected by VAD hysteresis. Stop recording.")
                            break
                        else:
                            preroll_buffer.append(chunk)
                            if (time.time() - listen_start) > timeout:
                                print("[ORCHESTRATOR] Listening timed out. No speech detected.")
                                break

                    await asyncio.sleep(0.005)
                    
                if len(audio_buffer) == 0:
                    if hasattr(self.audio_source, "is_exhausted") and self.audio_source.is_exhausted():
                        print("[RecordedAudio] End of recording reached.")
                        print("[ORCHESTRATOR] Recorded audio test completed.")
                        raise EOFError("Recorded audio input stream reached end of file.")
                    return {"status": "empty_input"}
                    
                captured_audio_bytes = bytes(audio_buffer)
                transcription = self.speech_recognizer.transcribe(captured_audio_bytes)

        
        if not transcription:
            return {"status": "empty_input"}

        raw_text = transcription
        # Normalize raw transcribed text (strip trailing punctuation, etc.)
        t_norm_start = time.time()
        from src.core.utils.normalizer import CommandNormalizer
        transcription = CommandNormalizer.normalize_transcript(transcription)
        normalized_text = transcription
        t_norm = time.time() - t_norm_start
        print(f"[PERF] Normalization latency: {t_norm * 1000:.2f}ms")
        
        if not transcription:
            return {"status": "empty_input"}

        # Check for emergency stop keyword on the raw transcript before anything else (SAFE-6)
        if transcription.strip().lower() == "stop":
            print("[ORCHESTRATOR] Global emergency STOP keyword recognized!")
            self.speech_synthesizer.stop()
            self.mode_manager.emergency_stop()
            self.speech_synthesizer.speak("Emergency stop activated. Switched to command mode.")
            res = {"status": "emergency_stop"}
            self._log_utterance(captured_audio_bytes, raw_text, normalized_text, max_vad_prob or 1.0, res)
            return res

        # ModeManager owns confirmation state and all transcript routing.
        t_route_start = time.time()
        route_result = self.mode_manager.route_transcript(transcription)
        t_route = time.time() - t_route_start
        print(f"[PERF] Intent routing & execution latency: {t_route:.3f}s")

        self._log_utterance(captured_audio_bytes, raw_text, normalized_text, max_vad_prob or 1.0, route_result)
        return route_result

    def _log_utterance(
        self,
        audio_buffer: bytes,
        raw_text: str,
        normalized_text: str,
        vad_prob: float,
        route_result: Dict[str, Any]
    ) -> None:
        """Structured per-utterance logging to logs/session.jsonl."""
        try:
            import datetime
            import json
            import os
            import numpy as np

            timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            device_id = getattr(self.audio_source, "active_device", None)
            if device_id is None:
                device_id = getattr(self.audio_source, "requested_device", "default")
            device_str = str(device_id)

            duration = 0.0
            rms = 0.0
            if audio_buffer:
                duration = round(len(audio_buffer) / (2 * 16000), 3)
                try:
                    samples = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float64)
                    if len(samples) > 0:
                        rms = round(float(np.sqrt(np.mean(samples ** 2))), 2)
                except Exception:
                    pass

            lang = getattr(self.speech_recognizer, "last_language", "en") or "en"
            lang_prob = getattr(self.speech_recognizer, "last_language_probability", 1.0)
            if lang_prob is None:
                lang_prob = 1.0
            lang_prob = round(float(lang_prob), 4)

            action = route_result.get("action")
            intent = "unknown"
            confidence = 1.0
            if isinstance(action, dict):
                intent = action.get("action", intent)
                confidence = float(action.get("intent_confidence", 1.0))
            elif route_result.get("status"):
                intent = str(route_result.get("status"))

            result_val = route_result.get("result", route_result.get("status"))

            log_entry = {
                "timestamp": timestamp,
                "device": device_str,
                "rms": rms,
                "vad_prob": round(float(vad_prob), 4),
                "duration": duration,
                "raw_text": raw_text,
                "language": lang,
                "language_prob": lang_prob,
                "normalized_text": normalized_text,
                "intent": intent,
                "confidence": confidence,
                "action": action,
                "result": result_val,
            }

            # Never log audio unless self.keep_audio is True
            if self.keep_audio and audio_buffer:
                import wave
                os.makedirs("logs/audio", exist_ok=True)
                audio_filename = f"logs/audio/utterance_{int(time.time() * 1000)}.wav"
                with wave.open(audio_filename, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_buffer)
                log_entry["audio_path"] = audio_filename

            log_dir = os.path.dirname(self.session_log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            with open(self.session_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            pass


    async def main_loop(self):
        """Infinite running loop simulating continuous operation."""
        print("[ORCHESTRATOR] Starting voice accessibility operator loop...")
        self.speech_synthesizer.speak("Operator system initialized. Ready.")
        
        try:
            while True:
                try:
                    # Capture audio and run step
                    result = await self.run_single_step()
                    if result and result.get("status") == "exit_requested":
                        print("[ORCHESTRATOR] Exit requested by user voice command. Shutting down.")
                        break
                    await asyncio.sleep(0.5)
                except EOFError:
                    print("[ORCHESTRATOR] Input stream closed (EOF). Exiting.")
                    break
                except KeyboardInterrupt:
                    print("\n[ORCHESTRATOR] Shutting down.")
                    break
                except Exception as e:
                    print(f"[ORCHESTRATOR] Pipeline error: {e}", file=sys.stderr)
                    self.speech_synthesizer.speak("An internal system error occurred.")
                    await asyncio.sleep(1.0)
        finally:
            if hasattr(self.audio_source, "stop_stream"):
                try:
                    self.audio_source.stop_stream()
                except Exception:
                    pass
