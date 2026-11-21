import pytest
import time
from src.adapters.windows_control import WindowsOSController
from tests.test_windows_control import is_interactive_session

@pytest.mark.integration
def test_real_windows_notepad_lifecycle():
    """Launches Notepad, switch focus, types text, checks dialog box, and force closes it."""
    if not is_interactive_session():
        pytest.skip("Skipping interactive window test: No active window station/desktop detected (headless session).")
        
    os_ctrl = WindowsOSController()
    
    try:
        # 1. Open Notepad
        res = os_ctrl.execute_action({"action": "open_app", "target": "notepad"})
        assert res["success"] is True
        assert os_ctrl.active_app == "notepad"
        
        time.sleep(1.5)
        
        # 2. Switch Focus
        res_switch = os_ctrl.execute_action({"action": "switch_app", "target": "notepad"})
        assert res_switch["success"] is True
        
        # 3. Type text
        typed = os_ctrl.type_text("Hello from real windows automation integration test!")
        assert typed is True
        
        # 4. Attempt clean close.
        # On Windows 11 UWP Notepad, unsaved text is auto-saved in session draft state and exits cleanly (success: True).
        # On Windows 10 legacy Notepad, an unsaved dialog block is spawned (success: False, error_type: dialog_detected).
        res_close = os_ctrl.execute_action({"action": "close_app", "target": "notepad"})
        assert (res_close["success"] is True) or (res_close.get("error_type") == "dialog_detected")
        
    finally:
        # 5. Clean up process
        os_ctrl.execute_action({
            "action": "close_app", 
            "target": "notepad", 
            "parameters": {"force": True}
        })
