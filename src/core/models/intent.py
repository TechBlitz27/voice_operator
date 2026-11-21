from typing import Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field

# Valid action types
ActionType = Literal[
    "open_app",
    "close_app",
    "switch_app",
    "minimize_app",
    "maximize_app",
    "list_open_apps",
    "what_is_in_front",
    "delete_file",
    "send_email",
    "read_document",
    "navigate_document",
    "type_text",
    "undo_last_action",
    "exit_operator",
    "ambiguous",
    "unknown"
]

class LLMIntent(BaseModel):
    """Schema representing structured intent produced by LLM parser (constrained by GBNF grammar)."""
    model_config = ConfigDict(extra="forbid")

    intent_confidence: float = Field(
        ..., ge=0.5, le=1.0,
        description="Confidence score for the parsed intent (0.5 to 1.0). Scores below 0.5 fail validation."
    )
    action: ActionType = Field(
        ..., 
        description="Action type matched from speech."
    )
    target: str = Field(
        default="", max_length=512,
        description="Target subject or name (e.g., application name, file path, email address)."
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Key-value parameters related to the action execution."
    )


class ExecutorAction(LLMIntent):
    """Internal schema sent to executor, containing lookup-derived confirmation flags."""
    requires_confirmation: bool = Field(
        ..., 
        description="Flag indicating if the action requires explicit spoken confirmation."
    )
