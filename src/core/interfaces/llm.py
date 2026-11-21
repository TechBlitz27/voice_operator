from abc import ABC, abstractmethod
from typing import Dict, Any

class LLMProvider(ABC):
    """Interface for querying local LLM and enforcing structured action schema."""

    @abstractmethod
    def generate_action(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Queries local LLM using grammar/schema constraint to parse natural speech into action objects.

        Args:
            prompt: User speech transcription text.
            schema: Dictionary representing the expected JSON validation schema.

        Returns:
            Dictionary matching the requested JSON validation schema structure.
        """
        pass
