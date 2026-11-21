import pyttsx3
import threading
import queue
import time
from typing import Callable, List, Optional
from src.core.interfaces.speech import SpeechSynthesizer


class TTSHandle:
    """Handle returned by speak() allowing caller to wait for speech synthesis completion."""

    def __init__(self, done_event: threading.Event):
        self._done_event = done_event

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Blocks until speech playback finishes or timeout expires. Returns True if finished."""
        return self._done_event.wait(timeout=timeout)

    @property
    def is_done(self) -> bool:
        return self._done_event.is_set()


class SAPITTS(SpeechSynthesizer):
    """Production Windows SAPI5 Speech Synthesizer using native COM SAPI.SpVoice.
    Supports asynchronous non-blocking playback, immediate purge stop, volume ducking,
    and speech completion callbacks.
    """

    def __init__(self):
        self._is_speaking = False
        self._cmd_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._speaker = None
        self._engine = None
        self.tts_start_time = 0.0
        self._speech_end_callbacks: List[Callable[[], None]] = []

        # Start background worker thread with COM STA apartment
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()
        time.sleep(0.3)

    def add_on_speech_end_listener(self, callback: Callable[[], None]) -> None:
        """Registers a callback invoked immediately when speech stream completes."""
        self._speech_end_callbacks.append(callback)

    def set_volume(self, volume_percent: int) -> None:
        """Sets SAPI voice volume (0 to 100). Useful for ducking volume when listening for stops."""
        if self._speaker:
            try:
                self._speaker.Volume = max(0, min(100, int(volume_percent)))
            except Exception:
                pass

    def speak(self, text: str, interruptible: bool = True, block: bool = False) -> TTSHandle:
        """Queues text to speak and clears pending queue if interruptible.
        Returns a TTSHandle whose wait() blocks until SAPI Status.RunningState is done.
        """
        if interruptible:
            self.stop()

        done_event = threading.Event()
        self._stop_event.clear()
        self._is_speaking = True
        self._cmd_queue.put((text, done_event))

        handle = TTSHandle(done_event)
        if block:
            handle.wait()
        return handle

    def stop(self) -> None:
        """Aborts speaking task immediately using SAPI Speak("", 2) purge flag and clears queue."""
        self._stop_event.set()
        while not self._cmd_queue.empty():
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break

        # If native SAPI COM speaker is running, immediately purge
        if self._speaker:
            try:
                self._speaker.Speak("", 2)  # 2 = SVSFPurgeBeforeSpeak
            except Exception:
                pass

        self._is_speaking = False

    def close(self) -> None:
        """Stops playback and shuts down background worker thread."""
        self.stop()
        self._cmd_queue.put(("__EXIT__", threading.Event()))
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)

    def is_speaking(self) -> bool:
        """Returns True if the engine is currently speaking or queue is active."""
        if self._speaker:
            try:
                # SAPI Status.RunningState: 1 = SPRS_DONE, 2 = SPRS_IS_SPEAKING
                if self._speaker.Status.RunningState == 2:
                    return True
            except Exception:
                pass
        return self._is_speaking or not self._cmd_queue.empty()

    def _worker_loop(self):
        """Worker loop running in a dedicated thread with STA COM initialization."""
        import pythoncom
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        except Exception:
            pythoncom.CoInitialize()

        try:
            import win32com.client
            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            self._speaker.Volume = 100
            self._speaker.Rate = 1
        except Exception as e:
            print(f"[SAPITTS] win32com SAPI.SpVoice init failed ({e}), falling back to pyttsx3")
            try:
                import pyttsx3
                self._engine = pyttsx3.init('sapi5')
                self._engine.setProperty('rate', 165)
                self._engine.setProperty('volume', 1.0)
            except Exception as e2:
                print(f"[SAPITTS] pyttsx3 init failed: {e2}")

        while True:
            try:
                item_tuple = self._cmd_queue.get()
                text, done_event = item_tuple

                if text == "__EXIT__":
                    self._is_speaking = False
                    done_event.set()
                    self._cmd_queue.task_done()
                    break

                if self._stop_event.is_set():
                    self._stop_event.clear()
                    self._is_speaking = False
                    done_event.set()
                    self._cmd_queue.task_done()
                    continue

                if text:
                    self._is_speaking = True
                    self._stop_event.clear()
                    self.tts_start_time = time.time()

                    if self._speaker:
                        # 1 = SVSFlagsAsync
                        self._speaker.Speak(text, 1)
                        # Poll until complete (RunningState == 1) or stop signaled
                        while True:
                            if self._stop_event.is_set():
                                self._speaker.Speak("", 2)  # SVSFPurgeBeforeSpeak
                                break
                            try:
                                if self._speaker.Status.RunningState == 1:
                                    break
                            except Exception:
                                break
                            time.sleep(0.015)
                    elif self._engine:
                        self._engine.say(text)
                        self._engine.runAndWait()

                    self._is_speaking = False
                    done_event.set()

                    # Trigger on_speech_end callbacks
                    for cb in self._speech_end_callbacks:
                        try:
                            cb()
                        except Exception as cb_err:
                            print(f"[SAPITTS] Error in speech_end callback: {cb_err}")

                self._cmd_queue.task_done()
            except Exception as e:
                self._is_speaking = False
                time.sleep(0.05)

        pythoncom.CoUninitialize()
