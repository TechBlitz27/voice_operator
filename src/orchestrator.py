import asyncio
import sys
import time
from typing import Dict, Any, Optional
from src.core.interfaces.audio import AudioSource, VoiceActivityDetector
from src.core.interfaces.speech import SpeechRecognizer, SpeechSynthesizer
from src.core.state_machine.mode_manager import ModeManager
from src.core.models.intent import ExecutorAction

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
        session_log_path: str = "logs/session.jsonl"
    ):
        self.audio_source = audio_source
        self.vad = vad
        self.speech_recognizer = speech_recognizer
        self.speech_synthesizer = speech_synthesizer
        self.mode_manager = mode_manager
        self.keep_audio = keep_audio
        self.session_log_path = session_log_path
        
        # Conversational state tracking for confirmation flows
        self.pending_confirm_action: Optional[Dict[str, Any]] = None
        self.confirm_state: Optional[str] = None  # None, "action_confirm", "force_close_confirm"

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
                preroll_buffer = collections.deque(maxlen=8)
                self.audio_source.start_stream()
                
                speech_started = False
                speech_start_time = 0.0
                speech_consecutive_frames = 0
                silence_frames = 0
                is_dictation = getattr(self.mode_manager, "current_mode", "command") == "dictation"
                max_silence_frames = 32 if is_dictation else 16
                max_record_duration = 15.0  # Capped at 15 s per requirement
                
                listen_start = time.time()
                timeout = 10.0  # Listen up to 10 seconds for user speech to start
                was_speaking = False
                
                try:
                    while True:
                        # 6. Speaker mode: Discard mic frames while TTS is playing
                        if hasattr(self.speech_synthesizer, "is_speaking") and self.speech_synthesizer.is_speaking():
                            was_speaking = True
                            listen_start = time.time()
                            speech_consecutive_frames = 0
                            preroll_buffer.clear()
                            if hasattr(self.audio_source, "flush"):
                                self.audio_source.flush()
                            await asyncio.sleep(0.02)
                            continue

                        if was_speaking:
                            # 6. Discard for 400 ms after playback actually ends, and flush queue
                            await asyncio.sleep(0.40)
                            if hasattr(self.audio_source, "flush"):
                                self.audio_source.flush()
                            else:
                                while hasattr(self.audio_source, "_audio_queue") and not self.audio_source._audio_queue.empty():
                                    try:
                                        self.audio_source._audio_queue.get_nowait()
                                    except Exception:
                                        break
                            was_speaking = False
                            listen_start = time.time()
                            speech_consecutive_frames = 0
                            preroll_buffer.clear()
                            continue

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
                            speech_consecutive_frames += 1
                            if not speech_started and speech_consecutive_frames >= 2:
                                print("[ORCHESTRATOR] Speech detected. Recording...")
                                speech_started = True
                                speech_start_time = time.time()
                                # Attach pre-roll audio so initial phonemes are preserved
                                for pre_chunk in preroll_buffer:
                                    audio_buffer.extend(pre_chunk)
                                preroll_buffer.clear()
                            if speech_started:
                                audio_buffer.extend(chunk)
                                if (time.time() - speech_start_time) >= max_record_duration:
                                    print("[ORCHESTRATOR] Maximum utterance duration reached. Stop recording.")
                                    break
                            silence_frames = 0
                        else:
                            speech_consecutive_frames = 0
                            if speech_started:
                                audio_buffer.extend(chunk)
                                silence_frames += 1
                                if silence_frames >= max_silence_frames or (time.time() - speech_start_time) >= max_record_duration:
                                    recorded_dur = time.time() - speech_start_time
                                    # Enforce 300 ms minimum speech length
                                    if recorded_dur < 0.30:
                                        print(f"[ORCHESTRATOR] Discarding short audio burst ({recorded_dur*1000:.0f}ms < 300ms min).")
                                        speech_started = False
                                        speech_start_time = 0.0
                                        silence_frames = 0
                                        audio_buffer.clear()
                                        preroll_buffer.clear()
                                        continue
                                    print("[ORCHESTRATOR] Silence detected. Stop recording.")
                                    break
                            else:
                                preroll_buffer.append(chunk)
                                if (time.time() - listen_start) > timeout:
                                    print("[ORCHESTRATOR] Listening timed out. No speech detected.")
                                    break
                                    
                        await asyncio.sleep(0.01)
                finally:
                    self.audio_source.stop_stream()
                    
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
            self.mode_manager.set_mode("command")
            self.pending_confirm_action = None
            self.confirm_state = None
            self.speech_synthesizer.speak("Emergency stop activated. Switched to command mode.")
            res = {"status": "emergency_stop"}
            self._log_utterance(captured_audio_bytes, raw_text, normalized_text, max_vad_prob or 1.0, res)
            return res

        # 2. Check if we are currently waiting for a safety confirmation
        if self.confirm_state is not None:
            res = self._handle_confirmation_input(transcription)
            self._log_utterance(captured_audio_bytes, raw_text, normalized_text, max_vad_prob or 1.0, res)
            return res

        # 3. Route transcript according to current mode state
        t_route_start = time.time()
        route_result = self.mode_manager.route_transcript(transcription)
        t_route = time.time() - t_route_start
        print(f"[PERF] Intent routing & execution latency: {t_route:.3f}s")
        
        # 4. Check if the routing result requires subsequent confirmation
        status = route_result.get("status")
        if status == "awaiting_confirmation":
            self.confirm_state = "action_confirm"
            self.pending_confirm_action = route_result.get("action")
        elif status == "awaiting_force_close_confirmation":
            self.confirm_state = "force_close_confirm"
            self.pending_confirm_action = route_result.get("action")

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


    def _handle_confirmation_input(self, transcription: str) -> Dict[str, Any]:
        """Processes user voice response when in an active safety confirmation state."""
        response = transcription.strip().lower()
        action = self.pending_confirm_action
        
        positive_confirmations = {
            "yes", "yes please", "confirm", "do it", "force close", "close it",
            "sure", "yeah", "yep", "ok", "okay", "please do", "ha", "haan", "sahi hai"
        }
        negative_confirmations = {
            "no", "no thanks", "cancel", "don't", "dont", "stop", "nevermind",
            "negative", "abort", "reject", "nah", "nope", "nahi", "mat karo"
        }
        
        if response in positive_confirmations:
            print(f"[ORCHESTRATOR] User confirmed action '{action.get('action')}' with '{response}'.")
            state = self.confirm_state
            self.confirm_state = None
            self.pending_confirm_action = None
            
            if state == "action_confirm":
                action["requires_confirmation"] = False
                result = self.mode_manager._execute_action_with_feedback(
                    ExecutorAction(**action)
                )
                return {"status": "executed_confirmed", "result": result}
                
            elif state == "force_close_confirm":
                action["parameters"] = {"force": True}
                action["requires_confirmation"] = False
                result = self.mode_manager._execute_action_with_feedback(
                    ExecutorAction(**action)
                )
                return {"status": "executed_force_close", "result": result}
                
        elif response in negative_confirmations:
            print(f"[ORCHESTRATOR] User canceled/rejected action '{action.get('action')}' with '{response}'.")
            self.confirm_state = None
            self.pending_confirm_action = None
            self.speech_synthesizer.speak("Action canceled.")
            return {"status": "canceled"}
            
        else:
            # Unrelated command/sentence spoken while confirmation was pending
            # 1. Cancel the dangerous pending action to preserve safety
            print(f"[ORCHESTRATOR] Pending confirmation canceled due to new command: '{transcription}'.")
            self.confirm_state = None
            self.pending_confirm_action = None
            self.speech_synthesizer.speak("Pending confirmation canceled.")
            
            # 2. Process the new spoken command separately so it is not swallowed
            return self.mode_manager.route_transcript(transcription)

    async def main_loop(self):
        """Infinite running loop simulating continuous operation."""
        print("[ORCHESTRATOR] Starting voice accessibility operator loop...")
        self.speech_synthesizer.speak("Operator system initialized. Ready.")
        
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
