from abc import ABC, abstractmethod

class AudioSource(ABC):
    """Interface for managing high-level audio stream capturing lifecycle."""
    
    @abstractmethod
    def start_stream(self) -> None:
        """Starts the audio capture stream."""
        pass

    @abstractmethod
    def read_chunk(self) -> bytes:
        """Reads a chunk of raw audio data from the active stream."""
        pass

    @abstractmethod
    def stop_stream(self) -> None:
        """Stops the audio capture stream."""
        pass


class VoiceActivityDetector(ABC):
    """Interface for detecting voice activity in real-time audio streams."""

    @abstractmethod
    def is_speech(self, audio_chunk: bytes) -> bool:
        """Determines if the provided audio chunk contains speech.
        
        Args:
            audio_chunk: Raw byte buffer containing audio samples.

        Returns:
            True if speech is detected, False otherwise.
        """
        pass
