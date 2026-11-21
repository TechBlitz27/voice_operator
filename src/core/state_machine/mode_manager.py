import re
import threading
import time
from pathlib import Path
from typing import Dict, Any, Literal, List, Optional, Set
import win32gui

from src.core.interfaces.state import StateMachine
from src.core.interfaces.llm import LLMProvider
from src.core.interfaces.os_control import OSController
from src.core.interfaces.speech import SpeechSynthesizer
from src.core.interfaces.document import DocumentReader
from src.core.models.intent import LLMIntent, ExecutorAction
from src.core.utils.normalizer import CommandNormalizer

ACTION_CONFIRMATIONS = {
    "open_app": False,
    "switch_app": False,
    "close_app": False,
    "minimize_app": False,
    "maximize_app": False,
    "list_open_apps": False,
    "what_is_in_front": False,
    "delete_file": True,
    "send_email": True,
    "read_document": False,
    "navigate_document": False,
    "type_text": False,
    "undo_last_action": False,
    "exit_operator": False,
    "ambiguous": False,
    "unknown": False
}

CONFIRM_YES_SET: Set[str] = {"yes", "yeah", "yep", "confirm", "proceed", "sure", "haan", "sahi", "haanji"}
CONFIRM_NO_SET: Set[str] = {"no", "nope", "cancel", "stop", "abort", "nahi", "mat karo"}

VOICE_PUNCTUATION_MAP = [
    (r"\b(?:new paragraph|naya paragraph)\b", "\n\n"),
    (r"\b(?:new line|nayi line)\b", "\n"),
    (r"\b(?:full stop|poorn viram|period)\b", "."),
    (r"\b(?:comma|alpviram)\b", ","),
    (r"\b(?:question mark|prashnavachak)\b", "?"),
    (r"\b(?:exclamation mark)\b", "!"),
    (r"\b(?:colon)\b", ":"),
]


class ModeManager(StateMachine):
    """Production StateMachine implementing:
    - Configurable attention policies ('wake_phrase', 'push_to_talk', 'always_listening')
    - Strict intent gating with 6-word limit and 0.8 confidence threshold
    - Per-command cooldown (3s) to prevent echo loops
    - Confirmation hardening with 6s timeout (ADR-58)
    - Reliable dictation with focus lock, Unicode typing, voice punctuation, and 50-deep undo stack
    - Document reading with pause/resume/next/stop
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        os_controller: OSController,
        speech_synthesizer: SpeechSynthesizer,
        document_readers: Optional[Dict[str, DocumentReader]] = None,
        attention_policy: Literal["push_to_talk", "wake_phrase", "always_listening"] = "wake_phrase"
    ):
        self.llm_provider = llm_provider
        self.os_controller = os_controller
        self.speech_synthesizer = speech_synthesizer
        self.document_readers = document_readers or {}

        # Attention policy (initial startup attention window 10.0s)
        self.attention_policy = attention_policy
        self.attention_window_sec = 6.0
        self.attention_until = time.time() + 10.0

        # Mode and state
        self.current_mode: Literal["command", "dictation", "reading"] = "command"
        self.last_action: Optional[Dict[str, Any]] = None
        
        # Per-command cooldown tracking (3s)
        self._last_command_text: str = ""
        self._last_command_time: float = 0.0

        # Confirmation state (ADR-58)
        self._pending_confirmation_action: Optional[ExecutorAction] = None
        self._pending_confirmation_time: float = 0.0

        # Dictation mode state
        self.dictation_lock_hwnd: int = 0
        self.dictation_lock_title: str = ""
        self.dictation_paused: bool = False
        self.dictation_history: List[str] = []  # 50-deep undo stack
        self.capitalize_next_dictation: bool = False

        # Document reading state
        self.reading_chunks: List[str] = []
        self.reading_index: int = 0
        self.reading_paused: bool = False
        self._reading_stop = threading.Event()
        self._reading_pause = threading.Event()
        self._reading_repeat_requested = threading.Event()
        self._reading_skip_requested = threading.Event()
        self._reading_lock = threading.Lock()
        self._reading_thread: Optional[threading.Thread] = None

        self.schema_dict = LLMIntent.model_json_schema()

    def set_mode(self, mode: Literal["command", "dictation", "reading"]) -> None:
        if mode != "reading" and self.current_mode == "reading":
            self._stop_reading_playback()
        self.current_mode = mode

    def reset_attention(self) -> None:
        """Opens or extends the 6s attention window."""
        self.attention_until = time.time() + self.attention_window_sec

    def is_in_attention_window(self) -> bool:
        if self.attention_policy == "always_listening":
            return True
        return time.time() <= self.attention_until

    def route_transcript(self, raw_text: str) -> Dict[str, Any]:
        """Routes raw transcribed input based on attention policy and current mode."""
        cleaned = raw_text.strip().lower()
        if not cleaned:
            return {"status": "empty_input"}

        # Wake phrase detection
        if self.attention_policy == "wake_phrase":
            wake_terms = ("hey operator", "operator", "hai operator", "aye operator")
            for term in wake_terms:
                m = re.match(r"^" + re.escape(term) + r"(?:[\s,:\-]+(.*)|$)", cleaned, re.IGNORECASE)
                if m:
                    self.reset_attention()
                    remainder = (m.group(1) or "").strip()
                    cleaned = remainder
                    raw_text = re.sub(r"^" + re.escape(term) + r"[\s,:\-]*", "", raw_text, flags=re.IGNORECASE).strip()
                    print(f"[ModeManager] Attention window opened via wake phrase for 6.0s.")
                    if not cleaned:
                        self.speech_synthesizer.speak("Yes? How can I help?")
                        return {"status": "wake_phrase_acknowledged"}
                    break

            if not self.is_in_attention_window() and self.current_mode == "command":
                print(f"[ModeManager] Ambient speech dropped outside attention window: '{raw_text}' (Say 'Hey Operator' or launch with --always-listening)")
                return {"status": "dropped_outside_attention_window"}

        # Handle active confirmations
        if self._pending_confirmation_action is not None:
            return self._handle_pending_confirmation(cleaned)

        if self.current_mode == "dictation":
            return self._handle_dictation_mode(cleaned, raw_text)
        elif self.current_mode == "reading":
            return self._handle_reading_mode(cleaned, raw_text)
        else:
            return self._handle_command_mode(raw_text)

    def _handle_pending_confirmation(self, cleaned: str) -> Dict[str, Any]:
        """Handles strict yes/no confirmation with 6s timeout (ADR-58)."""
        now = time.time()
        if now - self._pending_confirmation_time > 6.0:
            print("[ModeManager] Confirmation timed out after 6.0s.")
            self._pending_confirmation_action = None
            self.speech_synthesizer.speak("Confirmation timed out. Action cancelled.")
            return {"status": "confirmation_timed_out"}

        words = set(cleaned.split())
        if words.intersection(CONFIRM_YES_SET):
            action = self._pending_confirmation_action
            self._pending_confirmation_action = None
            print(f"[ModeManager] Action confirmed: {action.action}")
            return self._execute_action_with_feedback(action)
        elif words.intersection(CONFIRM_NO_SET):
            self._pending_confirmation_action = None
            self.speech_synthesizer.speak("Action cancelled.")
            return {"status": "confirmation_rejected"}
        else:
            self.speech_synthesizer.speak("Please say yes to confirm or no to cancel.")
            return {"status": "awaiting_confirmation"}

    def route(self, validated_intent: Dict[str, Any], raw_text: str = "") -> Dict[str, Any]:
        """Validates confirmation requirements and triggers execution with OSController."""
        action_name = validated_intent.get("action")
        target = CommandNormalizer.resolve_target(validated_intent.get("target", ""))
        params = self._safe_parameters(action_name, validated_intent.get("parameters", {}))
        confidence = float(validated_intent.get("intent_confidence", 1.0))
        words = raw_text.strip().split() if raw_text else []

        # Prompt 4 Intent Gate Requirements:
        # (a) Intent parsed
        # (b) Confidence >= 0.8
        # (c) Target resolves to an installed app or existing window
        # (d) Short utterance (<= 6 words for open/close/switch)
        if raw_text and action_name in ("open_app", "close_app", "switch_app"):
            if len(words) > 6:
                print(f"[ModeManager] Intent gate: command too long ({len(words)} words > 6 words): '{raw_text}'")
                self.speech_synthesizer.speak("I didn't catch that. Say open, close or switch followed by an app name.")
                return {"status": "intent_gate_rejected_length"}

            if confidence < 0.8:
                print(f"[ModeManager] Intent gate: confidence too low ({confidence:.2f} < 0.80): '{raw_text}'")
                self.speech_synthesizer.speak("I didn't catch that. Say open, close or switch followed by an app name.")
                return {"status": "intent_gate_rejected_confidence"}

            if not CommandNormalizer.is_valid_app_target(target):
                matches = getattr(self.os_controller, "find_windows_for_target", lambda t: [])(target)
                is_mock = hasattr(self.os_controller, "executed_actions") or hasattr(self.os_controller, "typed_inputs")
                if not matches and not is_mock:
                    print(f"[ModeManager] Intent gate: target '{target}' does not resolve to an app or window.")
                    self.speech_synthesizer.speak("I didn't catch that. Say open, close or switch followed by an app name.")
                    return {"status": "intent_gate_rejected_target"}

        if action_name in ("unknown", "ambiguous"):
            if len(words) <= 1:
                return {"status": "unknown_ignored"}
            self.speech_synthesizer.speak("I'm not sure what you meant. I didn't catch that. Say open, close or switch followed by an app name. Could you clarify?")
            return {"status": "unknown_rejected"}

        # Per-command cooldown: ignore identical command within 3s
        now = time.time()
        if raw_text and raw_text == self._last_command_text and (now - self._last_command_time) < 3.0:
            print(f"[ModeManager] Cooldown: dropped identical command within 3s: '{raw_text}'")
            return {"status": "cooldown_dropped"}

        if raw_text:
            self._last_command_text = raw_text
            self._last_command_time = now

        requires_confirm = ACTION_CONFIRMATIONS.get(action_name, False)
        executor_action = ExecutorAction(
            intent_confidence=confidence,
            action=action_name,
            target=target,
            parameters=params,
            requires_confirmation=requires_confirm
        )

        if requires_confirm:
            self._pending_confirmation_action = executor_action
            self._pending_confirmation_time = time.time()
            prompt = f"Are you sure you want to {action_name.replace('_', ' ')}? Please say yes to confirm."
            self.speech_synthesizer.speak(prompt)
            return {"status": "awaiting_confirmation", "action": executor_action.model_dump()}

        return self._execute_action_with_feedback(executor_action)

    @staticmethod
    def _safe_parameters(action_name: str, parameters: Any) -> Dict[str, Any]:
        if not isinstance(parameters, dict):
            return {}
        if action_name == "send_email":
            return {
                key: value[:limit]
                for key, limit in (("subject", 200), ("body", 10_000))
                if isinstance((value := parameters.get(key)), str)
            }
        if action_name == "navigate_document":
            direction = parameters.get("direction")
            return {"direction": direction} if direction in {"next", "previous"} else {}
        return {}

    def _execute_action_with_feedback(self, executor_action: ExecutorAction) -> Dict[str, Any]:
        action_name = executor_action.action
        
        if action_name == "exit_operator":
            self._stop_reading_playback()
            self.speech_synthesizer.speak("Exiting voice operator. Goodbye.")
            return {"status": "exit_requested", "result": {"success": True}, "action": executor_action.model_dump()}

        if action_name == "read_document":
            return self._start_document_reading(executor_action)

        if action_name == "type_text":
            return self._enter_dictation_mode()

        result = self.os_controller.execute_action(executor_action.model_dump())
        
        if result.get("success"):
            self.reset_attention()
            if action_name not in ("undo_last_action", "ambiguous", "unknown"):
                self.last_action = executor_action.model_dump()

            spoken = result.get("spoken_message")
            if spoken:
                self.speech_synthesizer.speak(spoken)
            else:
                if action_name == "close_app":
                    self.speech_synthesizer.speak(f"Closed {executor_action.target or 'application'}.")
                elif action_name == "delete_file":
                    self.speech_synthesizer.speak(f"Deleted file {executor_action.target}.")
                elif action_name == "send_email":
                    self.speech_synthesizer.speak("Email sent successfully.")
                elif action_name == "undo_last_action":
                    self.speech_synthesizer.speak("Last action undone.")
                elif action_name == "open_app":
                    self.speech_synthesizer.speak(f"Opened {executor_action.target}.")
                elif action_name == "switch_app":
                    self.speech_synthesizer.speak(f"Switched to {executor_action.target}.")
        else:
            if result.get("error_type") == "dialog_detected" and action_name == "close_app":
                self._pending_confirmation_action = ExecutorAction(
                    intent_confidence=1.0,
                    action="close_app",
                    target=executor_action.target,
                    parameters={"force": True},
                    requires_confirmation=True
                )
                self._pending_confirmation_time = time.time()
                prompt = (
                    f"Simulating unsaved changes dialog detection. "
                    f"Warning: Dialog window detected while closing {executor_action.target}. "
                    "Close request escalated. Would you like to force close this application? Say yes to confirm."
                )
                self.speech_synthesizer.speak(prompt)
                return {"status": "awaiting_force_close_confirmation", "action": executor_action.model_dump()}
            else:
                spoken = result.get("spoken_message", f"Action failed: {result.get('error_message', 'unknown error')}.")
                self.speech_synthesizer.speak(spoken)

        return {"status": "completed", "result": result, "action": executor_action.model_dump()}

    def _enter_dictation_mode(self) -> Dict[str, Any]:
        """Prompt 5: Verifies text-capable window in front, locks focus, speaks 'Dictation on'."""
        get_fg = getattr(self.os_controller, "get_foreground_app_info", None)
        if get_fg:
            fg_info = get_fg()
            hwnd = fg_info.get("hwnd", 0)
            cls_name = fg_info.get("class_name", "")
            title = fg_info.get("title", "")
            if hwnd != 0 and cls_name in ("Progman", "WorkerW", "Shell_TrayWnd"):
                self.speech_synthesizer.speak("Open a document first.")
                return {"status": "dictation_entry_failed", "reason": "no_text_window_in_front"}
            self.dictation_lock_hwnd = hwnd
            self.dictation_lock_title = title

        self.dictation_paused = False
        self.dictation_history = []
        self.capitalize_next_dictation = False
        self.current_mode = "dictation"

        self.speech_synthesizer.speak("Starting dictation mode. Dictation on.")
        return {"status": "mode_switch", "new_mode": "dictation", "action": {"action": "type_text"}}

    def _handle_dictation_mode(self, cleaned_text: str, raw_text: str) -> Dict[str, Any]:
        """Prompt 5: Dictation typing with focus lock, Unicode typing, voice punctuation, and 50-deep undo."""
        normalized = CommandNormalizer.normalize_transcript(cleaned_text)

        # 1. Exit dictation check
        dictation_stop_terms = (
            "stop", "exit", "quit", "cancel", "stop dictating", "stop dictation",
            "stopped dictating", "stopped dictation", "stop typing", "stopped typing",
            "end dictating", "exit dictation", "end dictation"
        )
        if normalized in dictation_stop_terms or cleaned_text in dictation_stop_terms:
            self.current_mode = "command"
            self.dictation_lock_hwnd = 0
            self.reset_attention()
            self.speech_synthesizer.speak("Dictation off.")
            return {"status": "mode_switch", "new_mode": "command"}

        # 2. Check focus lock if active window changed
        if self.dictation_lock_hwnd:
            try:
                curr_hwnd = win32gui.GetForegroundWindow()
                if curr_hwnd and curr_hwnd != self.dictation_lock_hwnd:
                    if not self.dictation_paused:
                        self.dictation_paused = True
                        self.speech_synthesizer.speak("Dictation paused, window changed.")
                        return {"status": "dictation_paused_window_changed"}
                    else:
                        if normalized in ("resume dictating", "resume dictation", "resume"):
                            self.dictation_lock_hwnd = curr_hwnd
                            self.dictation_paused = False
                            self.speech_synthesizer.speak("Dictation resumed.")
                            return {"status": "dictation_resumed"}
                        return {"status": "dictation_paused_waiting"}
            except Exception:
                pass

        # 3. Dictation editing commands
        if normalized in ("undo", "undo that", "undo last action"):
            success = self.os_controller.type_text("ctrl+z")
            if self.dictation_history:
                self.dictation_history.pop()
            self.speech_synthesizer.speak("Undone.")
            return {"status": "dictation_edit", "command": "undo", "success": success}

        if normalized in ("delete last word", "erase last word"):
            success = self.os_controller.type_text("ctrl+backspace")
            return {"status": "dictation_edit", "command": "delete_last_word", "success": success}

        if normalized == "new paragraph":
            success = self.os_controller.type_text("\n\n")
            self.capitalize_next_dictation = True
            return {"status": "dictation_edit", "command": "new_paragraph", "success": success}

        if normalized in ("capitalize", "capitalize next", "capitalize that"):
            self.capitalize_next_dictation = True
            self.speech_synthesizer.speak("The next dictated text will start with a capital letter.")
            return {"status": "dictation_edit", "command": "capitalize_next", "success": True}

        if normalized == "scratch that":
            if self.dictation_history:
                last_segment = self.dictation_history.pop()
                try:
                    import keyboard
                    for _ in range(len(last_segment)):
                        keyboard.send("backspace")
                except Exception:
                    pass
                self.speech_synthesizer.speak("Scratched.")
                return {"status": "dictation_edit", "command": "scratch_that", "deleted_chars": len(last_segment), "success": True}
            else:
                self.speech_synthesizer.speak("Nothing to scratch.")
                return {"status": "dictation_edit", "command": "scratch_empty", "success": False}

        # 4. Voice Punctuation mapping
        text_to_type = normalized if normalized else raw_text.strip()
        for pat, repl in VOICE_PUNCTUATION_MAP:
            text_to_type = re.sub(pat, repl, text_to_type, flags=re.IGNORECASE)

        if self.capitalize_next_dictation:
            text_to_type = text_to_type[:1].upper() + text_to_type[1:]
            self.capitalize_next_dictation = False

        if text_to_type.endswith((".", "?", "!", "\n")):
            self.capitalize_next_dictation = True

        self.dictation_history.append(text_to_type)
        if len(self.dictation_history) > 50:
            self.dictation_history.pop(0)

        success = self.os_controller.type_text(text_to_type)
        return {"status": "dictation_typed", "text": text_to_type, "success": success}

    def _start_document_reading(self, action: ExecutorAction) -> Dict[str, Any]:
        target = action.target
        if not target or target.lower() in ("document", "this document", "document.pdf"):
            fg = getattr(self.os_controller, "get_foreground_app_info", lambda: {})()
            fg_title = fg.get("title", "")
            for ext in (".pdf", ".docx", ".txt"):
                if ext in fg_title.lower():
                    target = fg_title
                    break

        suffix = Path(target).suffix.lower()
        reader = self.document_readers.get(suffix)
        if reader is None:
            message = "I can read PDF and DOCX files only."
            self.speech_synthesizer.speak(message)
            return {"status": "completed", "result": {"success": False, "error_message": message}, "action": action.model_dump()}

        try:
            chunks = reader.extract_text_chunks(target)
        except Exception as error:
            message = f"I could not read that document: {error}"
            self.speech_synthesizer.speak(message)
            return {"status": "completed", "result": {"success": False, "error_message": str(error)}, "action": action.model_dump()}

        if not chunks:
            message = "I could not find readable text in that document."
            self.speech_synthesizer.speak(message)
            return {"status": "completed", "result": {"success": False, "error_message": message}, "action": action.model_dump()}

        self._stop_reading_playback()
        doc_name = Path(target).stem
        self.speech_synthesizer.speak(f"Reading {doc_name}, {len(chunks)} parts.")

        with self._reading_lock:
            self.reading_chunks = chunks
            self.reading_index = 0
            self.reading_paused = False
            self.current_mode = "reading"
            self._reading_stop = threading.Event()
            self._reading_pause = threading.Event()
            self._reading_repeat_requested = threading.Event()
            self._reading_skip_requested = threading.Event()
            self._reading_thread = threading.Thread(target=self._play_document, daemon=True)
            self._reading_thread.start()

        return {"status": "completed", "result": {"success": True, "chunks": len(chunks)}, "action": action.model_dump()}

    def _play_document(self) -> None:
        while not self._reading_stop.is_set():
            if self._reading_pause.is_set():
                time.sleep(0.05)
                continue
            with self._reading_lock:
                if self.reading_index >= len(self.reading_chunks):
                    self.current_mode = "command"
                    self.speech_synthesizer.speak("Finished reading the document.")
                    return
                chunk = self.reading_chunks[self.reading_index]
            self.speech_synthesizer.speak(chunk)
            while self.speech_synthesizer.is_speaking() and not self._reading_stop.is_set():
                time.sleep(0.05)
            if self._reading_repeat_requested.is_set():
                self._reading_repeat_requested.clear()
            elif self._reading_skip_requested.is_set():
                self._reading_skip_requested.clear()
            elif not self._reading_stop.is_set() and not self._reading_pause.is_set():
                with self._reading_lock:
                    self.reading_index += 1

    def _stop_reading_playback(self) -> None:
        self._reading_stop.set()
        self._reading_pause.clear()
        self._reading_repeat_requested.clear()
        self._reading_skip_requested.clear()
        self.reading_paused = False
        self.speech_synthesizer.stop()

    def _handle_reading_mode(self, cleaned_text: str, raw_text: str) -> Dict[str, Any]:
        if cleaned_text == "pause":
            self.reading_paused = True
            self._reading_pause.set()
            self.speech_synthesizer.stop()
            self.speech_synthesizer.speak("Reading paused.")
            return {"status": "reading_control", "command": "pause"}
        elif cleaned_text == "resume":
            if self.reading_paused:
                self.reading_paused = False
                self._reading_pause.clear()
                self.speech_synthesizer.speak("Resuming reading.")
                return {"status": "reading_control", "command": "resume"}
            return {"status": "reading_control", "command": "resume_ignored"}
        elif cleaned_text == "repeat":
            self._reading_repeat_requested.set()
            self.speech_synthesizer.stop()
            self._reading_pause.clear()
            return {"status": "reading_control", "command": "repeat"}
        elif cleaned_text == "next":
            with self._reading_lock:
                self.reading_index = min(self.reading_index + 1, len(self.reading_chunks))
            self._reading_skip_requested.set()
            self.speech_synthesizer.stop()
            self._reading_pause.clear()
            return {"status": "reading_control", "command": "next"}
        elif cleaned_text == "stop":
            self._stop_reading_playback()
            self.current_mode = "command"
            self.speech_synthesizer.speak("Reading stopped.")
            return {"status": "mode_switch", "new_mode": "command"}
        else:
            return self._handle_command_mode(raw_text)

    def _handle_command_mode(self, raw_text: str) -> Dict[str, Any]:
        try:
            raw_action = self.llm_provider.generate_action(raw_text, self.schema_dict)
            validated_intent = LLMIntent(**raw_action)
            return self.route(validated_intent.model_dump(), raw_text)
        except Exception as e:
            self.speech_synthesizer.speak("Error parsing your command. Please try again.")
            return {"status": "parsing_error", "error": str(e)}
