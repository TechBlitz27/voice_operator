from typing import Dict, Any, List
from src.core.interfaces.os_control import OSController

class MockOSController(OSController):
    """Mock OS Controller for testing action executions without affecting the host OS."""

    def __init__(self):
        self.executed_actions: List[Dict[str, Any]] = []
        self.typed_inputs: List[str] = []
        self.active_app: str = "Desktop"

    def execute_action(self, action_schema: Dict[str, Any]) -> Dict[str, Any]:
        action_name = action_schema.get("action")
        target = action_schema.get("target", "")
        params = action_schema.get("parameters", {})
        
        self.executed_actions.append(action_schema)
        print(f"[MOCK OS] Executing action: {action_name} on target: '{target}' with parameters: {params}")

        # Simulate unsaved changes dialog safety scenario
        if action_name == "close_app" and target == "unsaved_word":
            print("[MOCK OS] Simulating unsaved changes dialog detection!")
            return {
                "success": False, 
                "error_type": "dialog_detected",
                "error_message": "Unsaved changes dialog detected."
            }

        # Simulate standard operations
        if action_name == "open_app":
            self.active_app = target
        elif action_name == "close_app":
            self.active_app = "Desktop"
        elif action_name == "switch_app":
            self.active_app = target

        return {"success": True, "active_app": self.active_app}

    def type_text(self, text: str) -> bool:
        self.typed_inputs.append(text)
        print(f"[MOCK OS] Typing text into active app ({self.active_app}): '{text}'")
        return True

    def resolve_window_selection(self, target: str, selection: str) -> Dict[str, Any]:
        selection_clean = selection.lower().strip()
        ordinal_map = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2}
        if selection_clean in ("close all", "all"):
            return {"success": True, "closed_count": 3, "spoken_message": f"Closed all windows of {target}."}
        if selection_clean in ordinal_map:
            idx = ordinal_map[selection_clean]
            return {"success": True, "closed_hwnd": 5001 + idx, "window_index": idx, "spoken_message": f"Closed {selection_clean} window of {target}."}
        return {"success": False, "spoken_message": f"Invalid selection: {selection}"}
