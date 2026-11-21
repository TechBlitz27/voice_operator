from abc import ABC, abstractmethod
from typing import Dict, Any

class OSController(ABC):
    """Interface for managing Windows UI automation actions and dictation."""

    @abstractmethod
    def execute_action(self, action_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a structured system action (open_app, close_app, switch_app, etc.).

        Args:
            action_schema: Action dictionary matching the executor-facing schemas.

        Returns:
            A status dictionary containing execution success metadata.
            e.g., {"success": True} or {"success": False, "error_type": "dialog_detected"}.
        """
        pass

    @abstractmethod
    def type_text(self, text: str) -> bool:
        """Injects text directly into the active field via dictation (bypasses LLM action routing).

        Args:
            text: Text string to type.

        Returns:
            True if text injection succeeded, False otherwise.
        """
        pass
