from unittest.mock import MagicMock, patch
import pytest

from src.adapters.windows_control import WindowsOSController


def test_known_app_target_does_not_fall_back_to_title_substring():
    """Known apps in APP_MAPPINGS must match by process name only, never title substring."""
    ctrl = WindowsOSController()

    # Mock visible windows where Chrome is not running, but Notepad has 'chrome' in its title
    mock_windows = [
        {
            "hwnd": 1001,
            "title": "Chrome Download Guide - Notepad",
            "class_name": "Notepad",
            "process_name": "notepad.exe",
            "is_minimized": False,
        },
        {
            "hwnd": 1002,
            "title": "Calculator",
            "class_name": "CalcFrame",
            "process_name": "calc.exe",
            "is_minimized": False,
        },
    ]

    with patch.object(ctrl, "enumerate_visible_windows", return_value=mock_windows):
        matches = ctrl.find_windows_for_target("chrome")
        # Must NOT return Notepad just because 'chrome' is in the title!
        assert matches == [], "Known app 'chrome' erroneously matched a window by title substring!"


def test_dialog_detection_scoped_to_target_process():
    """Unsaved changes dialog check must be scoped strictly to the target window's process."""
    ctrl = WindowsOSController()

    target_win = {
        "hwnd": 2001,
        "title": "My Document - Word",
        "class_name": "OpusApp",
        "process_name": "winword.exe",
        "is_minimized": False,
    }

    # Other process dialog (e.g. VS Code or Explorer dialog) with PID 9999
    unrelated_dialog = {
        "hwnd": 3001,
        "title": "Save As",
        "class_name": "#32770",
        "process_name": "code.exe",
        "is_minimized": False,
    }

    with patch.object(ctrl, "find_windows_for_target", return_value=[target_win]), \
         patch.object(ctrl, "is_elevated_window", return_value=False), \
         patch("win32process.GetWindowThreadProcessId", side_effect=lambda h: (1, 1234 if h == 2001 else 9999)), \
         patch.object(ctrl, "enumerate_visible_windows", return_value=[target_win, unrelated_dialog]), \
         patch("win32gui.PostMessage"), \
         patch("win32gui.IsWindow", side_effect=[True, True, False]), \
         patch("time.sleep"):

        res = ctrl._close_application("word", force=False)
        # Should NOT report dialog_detected because the #32770 dialog belongs to PID 9999, not target PID 1234
        assert res.get("error_type") != "dialog_detected"


def test_force_close_does_not_kill_entire_process():
    """Force-close must target the specific window (WM_DESTROY), never call psutil.Process.kill()."""
    ctrl = WindowsOSController()

    target_win = {
        "hwnd": 4001,
        "title": "Window 1 - Notepad",
        "class_name": "Notepad",
        "process_name": "notepad.exe",
        "is_minimized": False,
    }

    with patch.object(ctrl, "find_windows_for_target", return_value=[target_win]), \
         patch.object(ctrl, "is_elevated_window", return_value=False), \
         patch("win32process.GetWindowThreadProcessId", return_value=(1, 5555)), \
         patch("psutil.Process") as mock_psutil_proc, \
         patch("win32gui.PostMessage") as mock_post_msg, \
         patch("time.sleep"):

        res = ctrl._close_application("notepad", force=True)

        # psutil.Process.kill() must NEVER be called
        mock_psutil_proc.return_value.kill.assert_not_called()
        assert res["success"] is True


def test_disambiguation_handler_first_second_third_and_close_all():
    """Multi-window disambiguation must handle 'first', 'second', 'third', and 'close all'."""
    ctrl = WindowsOSController()

    windows = [
        {"hwnd": 5001, "title": "Doc1 - Notepad", "class_name": "Notepad", "process_name": "notepad.exe", "is_minimized": False},
        {"hwnd": 5002, "title": "Doc2 - Notepad", "class_name": "Notepad", "process_name": "notepad.exe", "is_minimized": False},
        {"hwnd": 5003, "title": "Doc3 - Notepad", "class_name": "Notepad", "process_name": "notepad.exe", "is_minimized": False},
    ]

    with patch.object(ctrl, "find_windows_for_target", return_value=windows), \
         patch.object(ctrl, "is_elevated_window", return_value=False), \
         patch("win32gui.PostMessage") as mock_post_msg, \
         patch("win32gui.IsWindow", return_value=False), \
         patch("time.sleep"):

        # 1. 'first' closes index 0 (hwnd 5001)
        res_first = ctrl.resolve_window_selection("notepad", selection="first")
        assert res_first["success"] is True
        assert res_first["closed_hwnd"] == 5001

        # 2. 'second' closes index 1 (hwnd 5002)
        res_second = ctrl.resolve_window_selection("notepad", selection="second")
        assert res_second["success"] is True
        assert res_second["closed_hwnd"] == 5002

        # 3. 'third' closes index 2 (hwnd 5003)
        res_third = ctrl.resolve_window_selection("notepad", selection="third")
        assert res_third["success"] is True
        assert res_third["closed_hwnd"] == 5003

        # 4. 'close all' closes all three windows
        res_all = ctrl.resolve_window_selection("notepad", selection="close all")
        assert res_all["success"] is True
        assert res_all["closed_count"] == 3


def test_mode_manager_disambiguation_voice_flow():
    """ModeManager processes user saying 'second' when awaiting multi-window disambiguation."""
    import time
    from src.adapters.mocks.os_control_mock import MockOSController
    from src.adapters.mocks.speech_mock import MockSpeechSynthesizer
    from src.adapters.mocks.llm_mock import MockLLMProvider
    from src.core.state_machine.mode_manager import ModeManager

    os_ctrl = MockOSController()
    tts = MockSpeechSynthesizer()
    llm = MockLLMProvider()
    mm = ModeManager(llm, os_ctrl, tts)

    mm._pending_disambiguation_target = "notepad"
    mm._pending_disambiguation_time = time.time()

    res = mm.route_transcript("second")
    assert res["status"] == "window_disambiguated"
    assert mm._pending_disambiguation_target is None
