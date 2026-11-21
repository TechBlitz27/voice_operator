from abc import ABC, abstractmethod
from typing import Dict, Any

class StateMachine(ABC):
    """Interface for routing user commands and dictations through modes and confirmation tiers."""

    @abstractmethod
    def route(self, validated_intent: Dict[str, Any]) -> Dict[str, Any]:
        """Processes a validated user action schema.
        
        Evaluates the action tier table, decides if spoken confirmation is required,
        and coordinates execution with the OSController.

        Args:
            validated_intent: Pydantic-validated intent dictionary.

        Returns:
            An executor action schema dictionary.
        """
        pass

    @abstractmethod
    def route_transcript(self, raw_text: str) -> Dict[str, Any]:
        """Entry point for transcribed speech text.
        
        Routes text depending on current operational mode:
        - Dictation mode: bypasses LLM; types directly.
        - Reading mode: checks for short low-latency keyword controls.
        - Command mode: forwards to LLM for intent parsing.

        Args:
            raw_text: Raw transcribed string from STT.

        Returns:
            An action or status dictionary representation of what was routed/processed.
        """
        pass
