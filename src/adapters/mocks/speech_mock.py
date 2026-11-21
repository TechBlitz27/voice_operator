import time
import threading
from typing import Optional, List
from src.core.interfaces.audio import AudioSource, VoiceActivityDetector
from src.core.interfaces.speech import SpeechRecognizer, SpeechSynthesizer

class MockAudioSource(AudioSource):
    """Mock Audio Source that simulates audio capture lifecycle."""
    
    def __init__(self):
        self.streaming = False
        
    def start_stream(self) -> None:
        self.streaming = True
        print("[MOCK AUDIO] Starting audio capture stream...")

    def read_chunk(self) -> bytes:
        if not self.streaming:
            raise RuntimeError("Stream not started")
        # Return dummy bytes
        time.sleep(0.1)
        return b'\x00' * 1024

    def stop_stream(self) -> None:
        self.streaming = False
        print("[MOCK AUDIO] Stopping audio capture stream.")


class MockVAD(VoiceActivityDetector):
    """Mock Voice Activity Detector that always detects speech after a short delay."""
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        return True


class MockSpeechRecognizer(SpeechRecognizer):
    """Mock Speech Recognizer that transcribes audio based on a text injection queue."""

    def __init__(self):
        self.transcription_queue: List[str] = []

    def queue_transcription(self, text: str) -> None:
        """Helper to simulate spoken input during automated testing."""
        self.transcription_queue.append(text)

    def transcribe(self, audio_data: bytes) -> str:
        if self.transcription_queue:
            text = self.transcription_queue.pop(0)
            print(f"[MOCK STT] Transcribed queued voice input: '{text}'")
            return text
            
        # Fallback to interactive console typing if no transcription is queued
        import sys
        if not sys.stdin or not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
            return ""
        try:
            print("\n--- [MOCK MIC] Speak now (type your command/dictation and press enter):")
            text = input("User voice input: ")
            return text
        except (EOFError, OSError):
            return ""


class MockDocumentReader:
    """Deterministic in-memory reader for mock CLI and state-machine tests."""

    def extract_text_chunks(self, file_path: str) -> List[str]:
        return [f"Mock document content from {file_path}."]


class MockSpeechSynthesizer(SpeechSynthesizer):
    """Mock Speech Synthesizer that prints text immediately and simulates time elapsed during speech."""

    def __init__(self):
        self._is_speaking = False
        self._speech_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def speak(self, text: str, interruptible: bool = True) -> None:
        self.stop()  # Stop any active playback first
        self._stop_event.clear()
        self._is_speaking = True
        
        # Print the entire message immediately so integration tests capture it instantly
        print(f"[MOCK TTS] Speaking: {text}")
        
        # Start a thread to simulate speaking duration so we can test interrupts
        self._speech_thread = threading.Thread(
            target=self._simulate_speaking_duration, 
            args=(text, interruptible), 
            daemon=True
        )
        self._speech_thread.start()

    def _simulate_speaking_duration(self, text: str, interruptible: bool) -> None:
        words = text.split()
        for _ in words:
            if interruptible and self._stop_event.is_set():
                print("[MOCK TTS] ... [INTERRUPTED]")
                self._is_speaking = False
                return
            time.sleep(0.15)  # Simulate word pacing
            
        self._is_speaking = False

    def stop(self) -> None:
        if self._is_speaking:
            self._stop_event.set()
            if self._speech_thread and hasattr(self._speech_thread, "_started") and self._speech_thread._started.is_set():
                try:
                    self._speech_thread.join(timeout=0.5)
                except RuntimeError:
                    pass
            self._is_speaking = False

    def is_speaking(self) -> bool:
        return self._is_speaking
