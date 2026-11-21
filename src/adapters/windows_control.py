import ctypes
import os
import psutil
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import win32con
import win32gui
import win32process
from send2trash import send2trash
from rapidfuzz import fuzz

from src.core.interfaces.os_control import OSController

APP_MAPPINGS = {
    "notepad": "notepad.exe",
    "word": "winword.exe",
    "chrome": "chrome.exe",
    "calculator": "calc.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "msedge": "msedge.exe",
    "explorer": "explorer.exe",
    "code": "code",
    "chatgpt": "https://chatgpt.com"
}

# Windows API constants for SendInput Unicode
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))
    ]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT)]


def send_unicode_string(text: str) -> bool:
    """Injects Unicode text reliably using Win32 SendInput KEYEVENTF_UNICODE."""
    try:
        user32 = ctypes.windll.user32
        for char in text:
            code = ord(char)
            # Key down
            inp_down = INPUT(type=INPUT_KEYBOARD)
            inp_down.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None)
            # Key up
            inp_up = INPUT(type=INPUT_KEYBOARD)
            inp_up.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None)
            user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
            user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))
            time.sleep(0.002)
        return True
    except Exception as e:
        print(f"[WindowsControl] SendInput Unicode error: {e}")
        return False


class WindowsOSController(OSController):
    """Production Windows OS Controller wrapping Win32 API, pywinauto, and UIAutomation.
    Features verified post-conditions, real top-level window resolution, elevation detection,
    and Unicode typing.
    """

    def __init__(self):
        self.active_app: str = "Desktop"
        self._last_launched_pids: List[int] = []
        self._deletion_roots = self._default_deletion_roots()

    @staticmethod
    def _default_deletion_roots() -> List[Path]:
        home = Path.home()
        candidates = [home / "Desktop", home / "Documents", home / "Downloads", home / "AppData" / "Local" / "Temp"]
        return [candidate.resolve() for candidate in candidates if candidate.exists()]

    def enumerate_visible_windows(self) -> List[Dict[str, Any]]:
        """Enumerates real visible top-level windows, ignoring invisible shells and tool windows."""
        visible_windows = []

        def enum_cb(hwnd, _):
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return True
            # Ignore tool windows, invisible shells, progman
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
            ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            if ex_style & win32con.WS_EX_TOOLWINDOW:
                return True
            cls_name = win32gui.GetClassName(hwnd)
            if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return True

            placement = win32gui.GetWindowPlacement(hwnd)
            is_minimized = (placement[1] == win32con.SW_SHOWMINIMIZED)

            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                proc = psutil.Process(pid)
                proc_name = proc.name()
            except Exception:
                proc_name = ""

            visible_windows.append({
                "hwnd": hwnd,
                "title": title,
                "class_name": cls_name,
                "process_name": proc_name,
                "is_minimized": is_minimized
            })
            return True

        win32gui.EnumWindows(enum_cb, None)
        return visible_windows

    def find_windows_for_target(self, target: str) -> List[Dict[str, Any]]:
        """Resolves target by process name first; only falls back to title match for non-known-app targets."""
        t_clean = target.lower().strip()
        all_windows = self.enumerate_visible_windows()
        is_known_app = t_clean in APP_MAPPINGS
        expected_exe = APP_MAPPINGS.get(t_clean, t_clean)
        if not expected_exe.endswith(".exe") and not expected_exe.startswith("http"):
            expected_exe = f"{expected_exe}.exe"

        # 1. Match by process name
        by_process = [w for w in all_windows if w["process_name"].lower() == expected_exe.lower()]
        if by_process:
            return by_process

        if is_known_app:
            # Never fall back to title substring matching for known application targets
            return []

        # 2. Match by title fuzz.ratio >= 85 or direct substring
        by_title = []
        for w in all_windows:
            title_lower = w["title"].lower()
            if t_clean in title_lower:
                by_title.append(w)
            elif fuzz.ratio(t_clean, title_lower) >= 85:
                by_title.append(w)

        return by_title

    def get_foreground_app_info(self) -> Dict[str, Any]:
        """Returns details about the current foreground window."""
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return {"hwnd": 0, "title": "Desktop", "process_name": "explorer.exe"}
        title = win32gui.GetWindowText(hwnd).strip()
        cls_name = win32gui.GetClassName(hwnd)
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = psutil.Process(pid).name()
        except Exception:
            proc_name = "unknown"
        return {"hwnd": hwnd, "title": title, "class_name": cls_name, "process_name": proc_name}

    def is_elevated_window(self, hwnd: int) -> bool:
        """Detects if a window is elevated or protected by UIPI."""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc = psutil.Process(pid)
            # If access denied on basic process attributes, it's elevated/system
            _ = proc.status()
            return False
        except psutil.AccessDenied:
            return True
        except Exception:
            return False

    def execute_action(self, action_schema: Dict[str, Any]) -> Dict[str, Any]:
        action_name = action_schema.get("action")
        target = action_schema.get("target", "").strip()
        params = action_schema.get("parameters", {})
        
        print(f"[WindowsOS] Executing: {action_name} on target: '{target}'")
        
        try:
            if action_name == "open_app":
                return self._open_application(target)
            elif action_name == "close_app":
                force = params.get("force", False)
                return self._close_application(target, force)
            elif action_name == "switch_app":
                return self._switch_application(target)
            elif action_name == "minimize_app":
                return self._minimize_application(target)
            elif action_name == "maximize_app":
                return self._maximize_application(target)
            elif action_name == "list_open_apps":
                return self._list_open_apps()
            elif action_name == "what_is_in_front":
                return self._what_is_in_front()
            elif action_name == "delete_file":
                return self._delete_file(target)
            elif action_name == "send_email":
                return self._send_email(target, params)
            elif action_name == "undo_last_action":
                return self._undo_last_action(target, params)
            else:
                return {"success": True, "info": "Action bypassed"}
        except Exception as e:
            return {"success": False, "error_message": str(e), "spoken_message": f"Action failed: {e}"}

    def _open_application(self, target: str) -> Dict[str, Any]:
        """Launches application and verifies post-condition: waits up to 5s for top-level visible window."""
        app_name = target.lower().strip()
        exe = APP_MAPPINGS.get(app_name, app_name)
        
        if exe.startswith("http://") or exe.startswith("https://"):
            try:
                os.startfile(exe)
                self.active_app = target
                return {"success": True, "spoken_message": f"Opened {target}."}
            except Exception as e:
                return {"success": False, "spoken_message": f"I couldn't open {target}."}

        # Launch executable
        launched = False
        try:
            os.startfile(exe)
            launched = True
        except OSError:
            if not exe.endswith(".exe"):
                try:
                    os.startfile(f"{exe}.exe")
                    launched = True
                except OSError:
                    pass

        if not launched:
            resolved_path = shutil.which(exe) or shutil.which(f"{exe}.exe")
            if resolved_path:
                try:
                    subprocess.Popen([resolved_path], shell=True)
                    launched = True
                except Exception:
                    pass

        if not launched:
            return {"success": False, "spoken_message": f"I couldn't open {target}."}

        # Post-condition verification: wait up to 5 seconds for a top-level visible window
        expected_proc = exe if exe.endswith(".exe") else f"{exe}.exe"
        t0 = time.time()
        while time.time() - t0 < 5.0:
            windows = self.find_windows_for_target(target)
            if windows:
                self.active_app = target
                return {"success": True, "active_app": target, "spoken_message": f"Opened {target}."}
            time.sleep(0.2)

        # Verification failed
        return {"success": False, "spoken_message": f"I couldn't open {target}."}

    def _close_application(self, target: str, force: bool = False) -> Dict[str, Any]:
        """Closes application, checking for unsaved changes dialog and verifying window no longer exists."""
        windows = self.find_windows_for_target(target)
        if not windows:
            msg = f"Window for {target} not found."
            return {"success": False, "spoken_message": msg, "error_message": msg}

        if len(windows) > 1 and not force:
            # Multi-window check
            return {
                "success": False,
                "requires_confirmation": True,
                "spoken_message": f"{target} has {len(windows)} windows. Say first, second or third, or say close all to close all."
            }

        target_win = windows[0]
        hwnd = target_win["hwnd"]

        if self.is_elevated_window(hwnd):
            return {"success": False, "spoken_message": "I can't control that window."}

        if force:
            try:
                # Force-close the specific single window (WM_DESTROY), never kill the entire process
                win32gui.PostMessage(hwnd, win32con.WM_DESTROY, 0, 0)
                time.sleep(0.5)
                return {"success": True, "spoken_message": f"Force closed {target}."}
            except Exception as e:
                return {"success": False, "spoken_message": f"Failed to force close {target}: {e}"}

        # Send WM_CLOSE
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(1.0)

        # Post-condition check: IsWindow still true?
        if win32gui.IsWindow(hwnd):
            # Check if dialog appeared specifically belonging to the target process
            dialog_found = False
            try:
                _, target_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                target_pid = None

            if target_pid:
                for w in self.enumerate_visible_windows():
                    try:
                        _, w_pid = win32process.GetWindowThreadProcessId(w["hwnd"])
                    except Exception:
                        continue
                    if w_pid == target_pid and (w["class_name"] == "#32770" or "save" in w["title"].lower()):
                        dialog_found = True
                        break

            if dialog_found:
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "error_type": "dialog_detected",
                    "spoken_message": f"{target} has unsaved changes. Would you like to force close? Say yes to confirm."
                }
            time.sleep(1.0)
            if win32gui.IsWindow(hwnd):
                return {"success": False, "spoken_message": f"Could not close {target}."}

        return {"success": True, "spoken_message": f"Closed {target}."}

    def resolve_window_selection(self, target: str, selection: str) -> Dict[str, Any]:
        """Handles disambiguation when multiple windows match target ('first', 'second', 'third', 'close all')."""
        windows = self.find_windows_for_target(target)
        if not windows:
            msg = f"Window for {target} not found."
            return {"success": False, "spoken_message": msg, "error_message": msg}

        selection_clean = selection.lower().strip()
        ordinal_map = {
            "first": 0, "1st": 0, "one": 0, "1": 0,
            "second": 1, "2nd": 1, "two": 1, "2": 1,
            "third": 2, "3rd": 2, "three": 2, "3": 2,
        }

        if selection_clean in ("close all", "all"):
            closed_count = 0
            for w in windows:
                hwnd = w["hwnd"]
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed_count += 1
            return {
                "success": True,
                "closed_count": closed_count,
                "spoken_message": f"Closed all {closed_count} windows of {target}."
            }

        if selection_clean in ordinal_map:
            idx = ordinal_map[selection_clean]
            if idx >= len(windows):
                return {
                    "success": False,
                    "spoken_message": f"{target} only has {len(windows)} windows."
                }
            target_win = windows[idx]
            hwnd = target_win["hwnd"]
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            return {
                "success": True,
                "closed_hwnd": hwnd,
                "window_index": idx,
                "spoken_message": f"Closed the {selection_clean} window of {target}."
            }

        return {
            "success": False,
            "spoken_message": f"Invalid selection '{selection}'. Say first, second, third, or close all."
        }

    def _switch_application(self, target: str) -> Dict[str, Any]:
        """Switches foreground focus to target, restoring if minimized, and verifies GetForegroundWindow."""
        windows = self.find_windows_for_target(target)
        if not windows:
            msg = f"Window for {target} not found."
            return {"success": False, "spoken_message": msg, "error_message": msg}

        if len(windows) > 1:
            print(f"[WindowsControl] Target '{target}' has {len(windows)} windows.")

        target_win = windows[0]
        hwnd = target_win["hwnd"]

        if self.is_elevated_window(hwnd):
            return {"success": False, "spoken_message": "I can't control that window."}

        # Restore if minimized
        if target_win["is_minimized"]:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        # SetForegroundWindow using AttachThreadInput and Alt-key workaround
        try:
            curr_fg = win32gui.GetForegroundWindow()
            if curr_fg != hwnd:
                user32 = ctypes.windll.user32
                curr_thread, _ = win32process.GetWindowThreadProcessId(curr_fg)
                target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
                user32.AttachThreadInput(curr_thread, target_thread, True)
                # Alt-key trick
                user32.keybd_event(win32con.VK_MENU, 0, 0, 0)
                win32gui.SetForegroundWindow(hwnd)
                user32.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
                user32.AttachThreadInput(curr_thread, target_thread, False)
        except Exception:
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

        time.sleep(0.3)
        # Post-condition verification
        active_hwnd = win32gui.GetForegroundWindow()
        if active_hwnd == hwnd or win32gui.GetWindowText(active_hwnd) == target_win["title"]:
            self.active_app = target
            return {"success": True, "active_app": target, "spoken_message": f"Switched to {target}."}
        else:
            return {"success": False, "spoken_message": f"Could not switch to {target}."}

    def _minimize_application(self, target: str) -> Dict[str, Any]:
        windows = self.find_windows_for_target(target)
        if not windows:
            msg = f"Window for {target} not found."
            return {"success": False, "spoken_message": msg, "error_message": msg}
        hwnd = windows[0]["hwnd"]
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        time.sleep(0.2)
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            return {"success": True, "spoken_message": f"Minimized {target}."}
        return {"success": False, "spoken_message": f"Could not minimize {target}."}

    def _maximize_application(self, target: str) -> Dict[str, Any]:
        windows = self.find_windows_for_target(target)
        if not windows:
            msg = f"Window for {target} not found."
            return {"success": False, "spoken_message": msg, "error_message": msg}
        hwnd = windows[0]["hwnd"]
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        time.sleep(0.2)
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMAXIMIZED:
            return {"success": True, "spoken_message": f"Maximized {target}."}
        return {"success": False, "spoken_message": f"Could not maximize {target}."}

    def _list_open_apps(self) -> Dict[str, Any]:
        windows = self.enumerate_visible_windows()
        names = []
        for w in windows:
            proc_clean = w["process_name"].replace(".exe", "").capitalize()
            if proc_clean not in names:
                names.append(proc_clean)
        list_str = ", ".join(names[:10])
        return {"success": True, "spoken_message": f"Open applications are: {list_str}."}

    def _what_is_in_front(self) -> Dict[str, Any]:
        info = self.get_foreground_app_info()
        return {"success": True, "spoken_message": f"In front is {info['title']}."}

    def type_text(self, text: str) -> bool:
        """Injects text into active window using SendInput Unicode."""
        if text == "":
            return True
        if text == "ctrl+z":
            import keyboard
            keyboard.send("ctrl+z")
            return True
        if text == "ctrl+backspace":
            import keyboard
            keyboard.send("ctrl+backspace")
            return True
        if text == "\n\n":
            import keyboard
            keyboard.press("enter", presses=2)
            return True
        return send_unicode_string(text)

    def _delete_file(self, target: str) -> Dict[str, Any]:
        try:
            path = Path(target).expanduser().resolve(strict=True)
            if not path.is_file():
                return {"success": False, "spoken_message": "Target is not a file."}
            if not any(path.is_relative_to(root) for root in self._deletion_roots):
                return {"success": False, "spoken_message": "Refusing to delete outside approved user folders."}
            send2trash(str(path))
            return {"success": True, "recycled": True, "spoken_message": f"Deleted {path.name}."}
        except FileNotFoundError:
            return {"success": False, "spoken_message": "File does not exist."}
        except Exception as e:
            return {"success": False, "spoken_message": f"Could not delete file: {e}"}

    def _send_email(self, target: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import win32com.client
            outlook = win32com.client.Dispatch("Outlook.Application")
            mail = outlook.CreateItem(0)
            mail.To = target
            mail.Subject = params.get("subject", "Voice Accessibility Operator Mail")
            mail.Body = params.get("body", "Sent via Accessibility Voice Operator.")
            mail.Send()
            return {"success": True, "spoken_message": "Email sent successfully."}
        except Exception as e:
            return {"success": False, "spoken_message": f"Outlook could not send the email: {e}"}

    def _undo_last_action(self, target: str, params: Dict[str, Any]) -> Dict[str, Any]:
        import keyboard
        keyboard.send("ctrl+z")
        return {"success": True, "spoken_message": "Last action undone."}
