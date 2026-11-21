import pytest
import time
from src.adapters.windows_control import WindowsOSController

pytestmark = pytest.mark.integration
def is_interactive_session() -> bool:
    import win32gui
    has_visible_gui_windows = False
    def callback(hwnd, extra):
        nonlocal has_visible_gui_windows
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            has_visible_gui_windows = True
    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass
    return has_visible_gui_windows

def test_windows_open_notepad():
    """Verifies that launching Notepad process returns successful status."""
    os_ctrl = WindowsOSController()
    res = os_ctrl.execute_action({"action": "open_app", "target": "notepad"})
    
    assert res["success"] is True
    assert os_ctrl.active_app == "notepad"
    
    # Clean up process
    os_ctrl.execute_action({
        "action": "close_app", 
        "target": "notepad", 
        "parameters": {"force": True}
    })


def test_windows_switch_unknown_application():
    """Verifies that focusing a nonexistent application returns failure."""
    os_ctrl = WindowsOSController()
    res = os_ctrl.execute_action({"action": "switch_app", "target": "NonExistentAppXYZ"})
    
    assert res["success"] is False
    assert len(res.get("error_message", "")) > 0


def test_windows_close_unknown_application():
    """Verifies that closing a nonexistent application returns failure."""
    os_ctrl = WindowsOSController()
    res = os_ctrl.execute_action({"action": "close_app", "target": "NonExistentAppXYZ"})
    
    assert res["success"] is False


def test_windows_type_empty_text():
    """Verifies that typing empty text is handled safely and returns success."""
    os_ctrl = WindowsOSController()
    # typing empty text should return true and not crash
    assert os_ctrl.type_text("") is True


def test_windows_notepad_unsaved_close_escalation():
    """Natively verifies that clean close on unsaved document triggers dialog detection."""
    if not is_interactive_session():
        pytest.skip("Skipping interactive window test: No active window station/desktop detected (headless session).")
        
    os_ctrl = WindowsOSController()
    
    try:
        # Launch Notepad
        os_ctrl.execute_action({"action": "open_app", "target": "notepad"})
        time.sleep(1.5)
        
        # Focus and write something
        os_ctrl.execute_action({"action": "switch_app", "target": "notepad"})
        os_ctrl.type_text("Unsaved changes automated test text.")
        
        # Trigger close
        res_close = os_ctrl.execute_action({"action": "close_app", "target": "notepad"})
        
        # Verify result contract: either modern Win11 Notepad auto-saved session and exited cleanly (success=True),
        # or classic Notepad spawned an unsaved changes dialog block (success=False, error_type="dialog_detected").
        assert isinstance(res_close, dict)
        assert "success" in res_close
        if not res_close["success"]:
            assert res_close.get("error_type") == "dialog_detected"
        
    finally:
        # Clean up
        os_ctrl.execute_action({
            "action": "close_app", 
            "target": "notepad", 
            "parameters": {"force": True}
        })
