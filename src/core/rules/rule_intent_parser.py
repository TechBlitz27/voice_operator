import re
from typing import Dict, Any
from src.core.interfaces.llm import LLMProvider

OFF_TOPIC_PATTERNS = [
    r"weather", r"hello", r"hi\b", r"hey\b", r"how are you", r"thank", r"play",
    r"tell me", r"joke", r"sing", r"news", r"who are you", r"what time", r"alarm",
    r"market", r"stocks", r"recipe", r"sports", r"score", r"google for", r"search for",
    r"what is", r"how to", r"why is", r"where is", r"can you hear me", r"testing",
    r"good morning", r"good night", r"bye bye", r"namaste",
]

class RuleIntentParser(LLMProvider):
    """Offline regex rules-tier parser for deterministic development and tests."""

    def generate_action(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = prompt.strip().lower()
        
        # Default unknown response
        unknown_result = {
            "intent_confidence": 0.50,
            "action": "unknown",
            "target": "",
            "parameters": {}
        }

        if not cleaned:
            return unknown_result

        # Check for explicit off-topic phrases
        for pat in OFF_TOPIC_PATTERNS:
            if re.search(pat, cleaned):
                return unknown_result

        # Regex mappings for simulating LLM intent parsing (English + Hindi/Hinglish)
        open_match = re.match(r"^(?:open|launch|start|kholo|chalu karo)\s+([a-zA-Z0-9\s_\.\-]+)$", cleaned) or re.match(r"^([a-zA-Z0-9\s_\.\-]+)\s+(?:kholo|chalu karo)$", cleaned)
        close_match = re.match(r"^(?:close|exit|quit|band karo|hatao)(?:\s+([a-zA-Z0-9\s_\.\-]+))?$", cleaned) or re.match(r"^([a-zA-Z0-9\s_\.\-]+)\s+(?:band karo|hatao)$", cleaned)
        switch_match = re.match(r"^(?:switch to|which to|which 2|which two|which|go to app|activate|switch|par jao)\s+([a-zA-Z0-9\s_\.\-]+)$", cleaned) or re.match(r"^([a-zA-Z0-9\s_\.\-]+)\s+(?:par switch karo|par jao)$", cleaned)
        delete_match = re.match(r"^(?:delete|remove|mitao)\s+(?:file\s+)?([a-zA-Z0-9\s_\.\-]+)$", cleaned)
        email_match = re.match(r"^(?:send email to|email)\s+([a-zA-Z0-9_\-\.]+@[a-zA-Z0-9_\-\.]+)$", cleaned)
        read_match = re.match(r"^(?:read|padho|sunao)(?:\s+this)?(?:\s+document)?(?:\s+file)?(?:\s+([a-zA-Z0-9\s_\.\-]+))?$", cleaned)
        
        exit_phrases = ("exit", "quit", "exit operator", "exit voice operator", "stop operator", "shutdown operator", "bye", "goodbye", "band karo operator")
        
        if cleaned in exit_phrases or (close_match and close_match.group(1) and close_match.group(1).strip() in ("operator", "voice operator", "system", "app")):
            return {
                "intent_confidence": 0.95,
                "action": "exit_operator",
                "target": "operator",
                "parameters": {}
            }
            
        elif any(phrase in cleaned for phrase in ("start dictating", "start dictation", "dictation", "start typing", "dictation shuru", "typing shuru")):
            return {
                "intent_confidence": 0.95,
                "action": "type_text",
                "target": "",
                "parameters": {}
            }
            
        elif open_match:
            app_name = open_match.group(1).strip()
            if app_name in ("file explorer", "files", "my computer", "explorer", "folder", "directories"):
                return {"intent_confidence": 0.95, "action": "open_app", "target": "explorer", "parameters": {}}
            elif app_name.endswith((".pdf", ".docx", ".txt")) or "document.pdf" in app_name or "guide.pdf" in app_name:
                return {"intent_confidence": 0.95, "action": "read_document", "target": app_name, "parameters": {}}
            else:
                return {"intent_confidence": 0.95, "action": "open_app", "target": app_name, "parameters": {}}
                
        elif close_match:
            app_name = close_match.group(1)
            target = app_name.strip() if app_name else "Word"
            return {"intent_confidence": 0.95, "action": "close_app", "target": target, "parameters": {}}
            
        elif switch_match:
            return {"intent_confidence": 0.95, "action": "switch_app", "target": switch_match.group(1).strip(), "parameters": {}}
            
        elif delete_match:
            return {"intent_confidence": 0.95, "action": "delete_file", "target": delete_match.group(1).strip(), "parameters": {}}
            
        elif email_match:
            return {"intent_confidence": 0.95, "action": "send_email", "target": email_match.group(1).strip(), "parameters": {}}
            
        elif read_match:
            tgt = read_match.group(1).strip() if read_match.group(1) else "document.pdf"
            return {"intent_confidence": 0.95, "action": "read_document", "target": tgt, "parameters": {}}
            
        elif "next paragraph" in cleaned or "skip" in cleaned:
            return {"intent_confidence": 0.95, "action": "navigate_document", "target": "", "parameters": {"direction": "next"}}
            
        elif cleaned in ("undo", "undo last action", "undo that"):
            return {"intent_confidence": 0.95, "action": "undo_last_action", "target": "", "parameters": {}}

        elif re.match(r"^(?:minimize|minimise)\s+(.+)$", cleaned):
            m = re.match(r"^(?:minimize|minimise)\s+(.+)$", cleaned)
            return {"intent_confidence": 0.95, "action": "minimize_app", "target": m.group(1).strip(), "parameters": {}}

        elif re.match(r"^(?:maximize|maximise|fullscreen)\s+(.+)$", cleaned):
            m = re.match(r"^(?:maximize|maximise|fullscreen)\s+(.+)$", cleaned)
            return {"intent_confidence": 0.95, "action": "maximize_app", "target": m.group(1).strip(), "parameters": {}}

        elif cleaned in ("list open apps", "list apps", "what apps are open", "show open apps"):
            return {"intent_confidence": 0.95, "action": "list_open_apps", "target": "", "parameters": {}}

        elif cleaned in ("what is in front", "what app is in front", "which app", "foreground app"):
            return {"intent_confidence": 0.95, "action": "what_is_in_front", "target": "", "parameters": {}}
            
        else:
            return unknown_result
