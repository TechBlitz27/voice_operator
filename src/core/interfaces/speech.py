from abc import ABC, abstractmethod

class SpeechRecognizer(ABC):
    """Interface for transcribing speech audio to text."""

    @abstractmethod
    def transcribe(self, audio_data: bytes) -> str:
        """Transcribes raw audio buffer into text.
        
        Args:
            audio_data: Raw byte buffer containing speech audio samples.

        Returns:
            The transcribed text representation.
        """
        pass


class SpeechSynthesizer(ABC):
    """Interface for text-to-speech output with playback control."""

    @abstractmethod
    def speak(self, text: str, interruptible: bool = True) -> None:
        """Speaks the text aloud.
        
        Args:
            text: Text to read.
            interruptible: If True, this speaking task can be halted early.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """Halts current audio synthesis immediately."""
        pass

    @abstractmethod
    def is_speaking(self) -> bool:
        """Checks if the synthesizer is currently actively speaking.
        
        Returns:
            True if speaking, False otherwise. Needed to avoid speech audio feedback loops.
        """
        pass
