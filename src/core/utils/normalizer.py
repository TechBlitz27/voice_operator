import os
import re
from typing import Optional, Set, Dict, Tuple
import yaml
from rapidfuzz import fuzz

CANONICAL_APPLICATIONS: Set[str] = {
    "chrome", "word", "excel", "code", "notepad", "calculator", "powerpoint", "msedge", "explorer", "chatgpt"
}

CLOSED_VERBS: Set[str] = {
    "open", "close", "switch", "start", "stop", "read", 
    "minimize", "maximize", "list", "what", "pause", "resume", 
    "repeat", "next", "scratch", "undo", "delete", "yes", "no"
}

FUZZY_THRESHOLD = 85

class CommandNormalizer:
    enable_regex_fallback: bool = True
    _hindi_lexicon: Optional[Dict[str, str]] = None

    @classmethod
    def _load_hindi_lexicon(cls) -> Dict[str, str]:
        """Loads Hindi-to-English transliteration lexicon from YAML file with in-memory caching."""
        if cls._hindi_lexicon is not None:
            return cls._hindi_lexicon

        lexicon: Dict[str, str] = {}
        # Built-in core mappings
        default_mappings = {
            "खोलो": "open", "kholo": "open", "kholiye": "open", "khol": "open", "khol do": "open",
            "बंद करो": "close", "band karo": "close", "band kijiye": "close", "band": "close", "बंद": "close",
            "बदलो": "switch", "badlo": "switch", "badliye": "switch",
            "शुरू करो": "start", "shuru karo": "start", "chalu karo": "start", "चालू करो": "start",
            "रोक दो": "stop", "roko": "stop", "rok do": "stop", "रुको": "stop", "ruko": "stop", "ruk jao": "stop",
            "पढ़ो": "read", "padho": "read", "padhiye": "read",
            "हाँ": "yes", "हां": "yes", "haan": "yes", "ha": "yes", "sahi": "yes",
            "नहीं": "no", "nahi": "no", "na": "no"
        }
        lexicon.update(default_mappings)

        lexicon_path = os.path.join("config", "hindi_lexicon.yaml")
        if os.path.exists(lexicon_path):
            try:
                with open(lexicon_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        for section in ("verbs", "control"):
                            if section in data and isinstance(data[section], dict):
                                lexicon.update({k.lower().strip(): v.lower().strip() for k, v in data[section].items()})
            except Exception as e:
                print(f"[NORMALIZER] Warning: Could not read {lexicon_path}: {e}")

        cls._hindi_lexicon = lexicon
        return cls._hindi_lexicon

    @classmethod
    def _apply_hindi_lexicon(cls, text: str) -> str:
        """Transliterates common Hindi command words into English canonical equivalents."""
        lexicon = cls._load_hindi_lexicon()
        # Sort keys by length descending to match multi-word phrases first
        sorted_keys = sorted(lexicon.keys(), key=lambda k: len(k), reverse=True)
        res = text
        for k in sorted_keys:
            v = lexicon[k]
            # Word boundary matching for Latin; direct substring for Devanagari
            if re.search(r'[\u0900-\u097F]', k):
                pattern = re.escape(k)
            else:
                pattern = r'\b' + re.escape(k) + r'\b'
            
            new_res = re.sub(pattern, v, res, flags=re.IGNORECASE)
            if new_res != res:
                print(f"[NORMALIZER] Hindi transliteration: '{k}' -> '{v}'")
                res = new_res
        return res

    @staticmethod
    def filter_garbage_scripts(text: str) -> str:
        """Rejects non-Latin and non-Devanagari garbage (e.g. Cyrillic, Arabic, Hebrew, CJK, Thai).
        Retains Latin, Devanagari, numbers, whitespace, and basic punctuation.
        """
        if not text:
            return ""

        # Check for forbidden foreign scripts (Cyrillic, Arabic, Hebrew, CJK, Thai, etc.)
        forbidden_pattern = re.compile(
            r'[\u0400-\u04FF\u0590-\u05FF\u0600-\u06FF\u0E00-\u0E7F\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF]'
        )
        if forbidden_pattern.search(text):
            # If transcript has foreign script characters, strip them out
            cleaned = forbidden_pattern.sub('', text).strip()
            # If nothing useful remains, drop it
            if not re.search(r'[a-zA-Z0-9\u0900-\u097F]', cleaned):
                print(f"[NORMALIZER] Dropped garbage non-Latin/non-Devanagari text: '{text}'")
                return ""
            text = cleaned

        return text

    @classmethod
    def fuzzy_match_verb(cls, word: str) -> Tuple[str, bool]:
        """Fuzzy-matches the candidate verb against CLOSED_VERBS using rapidfuzz fuzz.ratio (threshold 85)."""
        w_lower = word.lower().strip()
        if not w_lower:
            return word, False

        if w_lower in CLOSED_VERBS:
            return w_lower, False

        best_verb = None
        best_score = 0.0
        for verb in CLOSED_VERBS:
            score = fuzz.ratio(w_lower, verb)
            if score > best_score:
                best_score = score
                best_verb = verb

        if best_verb and best_score >= FUZZY_THRESHOLD:
            print(f"[NORMALIZER] Fuzzy corrected verb '{word}' -> '{best_verb}' (fuzz.ratio: {best_score:.1f})")
            return best_verb, True

        return word, False

    @classmethod
    def fuzzy_match_target(cls, target: str) -> Tuple[str, bool]:
        """Fuzzy-matches candidate target against known application names using rapidfuzz fuzz.ratio (threshold 85).
        Crucially, short words like 'on' will NOT match any app.
        """
        t_lower = target.lower().strip()
        if not t_lower:
            return target, False

        if t_lower in CANONICAL_APPLICATIONS:
            return t_lower, False

        # Pre-check: short words (< 3 chars) cannot fuzzy match longer app names at ratio >= 85
        if len(t_lower) < 3:
            return target, False

        best_app = None
        best_score = 0.0
        for app in CANONICAL_APPLICATIONS:
            score = fuzz.ratio(t_lower, app)
            if score > best_score:
                best_score = score
                best_app = app

        if best_app and best_score >= FUZZY_THRESHOLD:
            print(f"[NORMALIZER] Fuzzy corrected target '{target}' -> '{best_app}' (fuzz.ratio: {best_score:.1f})")
            return best_app, True

        return target, False

    @classmethod
    def normalize_transcript(cls, text: str) -> str:
        """Normalizes transcript:
        1. Filters non-Latin / non-Devanagari garbage.
        2. Transliterates Hindi command words to English.
        3. Strips punctuation, collapses duplicates, joins spaced letters.
        4. Data-driven fuzzy matching on first verb using rapidfuzz fuzz.ratio >= 85.
        5. Optional regex phonetic fallback if enabled.
        """
        if not text:
            return ""

        # Step 1: Filter foreign script garbage
        text = cls.filter_garbage_scripts(text)
        if not text:
            return ""

        # Step 2: Transliterate common Hindi command words
        text = cls._apply_hindi_lexicon(text)

        text = text.strip()
        # Strip leading and trailing punctuation & quotes
        text = re.sub(r"^[\s\.,\?!;:\"'—\-]+|[\s\.,\?!;:\"'—\-]+$", "", text).strip()
        
        # Join isolated single letters (e.g. "W O R D" -> "WORD")
        text = re.sub(r'(?<=\b[a-zA-Z])\s+(?=[a-zA-Z]\b)', '', text)
        
        # Collapse consecutive duplicate words (e.g. "word word" -> "word")
        text = re.sub(r'\b(\w+)(?:\s+\1)+\b', r'\1', text, flags=re.IGNORECASE).strip()

        # Step 3: Data-driven verb fuzzy normalization
        words = text.split()
        if words:
            first_word = words[0]
            canonical_verb, corrected = cls.fuzzy_match_verb(first_word)
            if corrected:
                words[0] = canonical_verb
                text = " ".join(words)

        # Step 4: Optional regex fallback behind flag
        if cls.enable_regex_fallback:
            phonetic_prefixes = [
                (r"^\bwhich\s+(?:to|2|two|the)\b", "switch to"),
                (r"^\bswitch\s+the\b", "switch to"),
                (r"^\bupon\s+xl\b", "open excel"),
                (r"^\baction\s+excel\b", "exit excel"),
                (r"^\bopanvie\s+escor\b", "open vs code"),
                (r"^\bstar(?:t)?\s+dictation\b", "start dictating"),
                (r"^\blord's\s+word\b", "close word"),
                (r"\b(?:that\s+they\s+|so\s+)?(?:stop|stopped|so|scorp)\s+(?:dictation|dictating|objectation|option|bictition)\b", "stop dictating"),
                (r"\b(?:stop|stopped)\s+(?:typing|type|writing)\b", "stop dictating"),
                (r"\b(?:close|open|switch(?:\s+to)?)\s+crow\b", lambda m: m.group(0).lower().replace("crow", "chrome")),
                (r"\bcrow\b", "chrome"),
            ]
            for pattern, replacement in phonetic_prefixes:
                match = re.search(pattern, text, flags=re.IGNORECASE)
                if match:
                    new_text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
                    print(f"[NORMALIZER] Regex fallback corrected '{text}' -> '{new_text}'")
                    text = new_text

        # Filter out system feedback / TTS self-talk echo phrases
        system_echo_patterns = [
            r"operator system initialized",
            r"could not launch",
            r"action failed",
            r"was not found on system",
            r"window for .* not found",
            r"starting dictation mode",
            r"dictation mode stopped",
            r"i'm not sure what you meant",
        ]
        for pattern in system_echo_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return ""

        return text.strip()

    @classmethod
    def resolve_target(cls, target: str) -> str:
        """Resolves target application name aliases to canonical names with article stripping and fuzzy matching."""
        if not target:
            return ""
        cleaned = target.strip().lower()
        # Strip trailing punctuation from target
        while cleaned and cleaned[-1] in (".", ",", "?", "!", ";", ":", "'", '"'):
            cleaned = cleaned[:-1]
        cleaned = cleaned.strip()

        # Strip harmless leading articles ("the", "a", "an")
        cleaned = re.sub(r'^(?:the|a|an)\s+', '', cleaned, flags=re.IGNORECASE).strip()

        # Apply letter joining and word de-duplication on target
        cleaned = re.sub(r'(?<=\b[a-zA-Z])\s+(?=[a-zA-Z]\b)', '', cleaned)
        cleaned = re.sub(r'\b(\w+)(?:\s+\1)+\b', r'\1', cleaned, flags=re.IGNORECASE).strip()
        
        # Hard alias mapping for common multi-word variants and specific names
        alias_mapping = {
            "note pad": "notepad",
            "load pad": "notepad",
            "northpad": "notepad",
            "north side": "notepad",
            "otepad": "notepad",
            "o-t-e-p-a-d": "notepad",
            "notepad": "notepad",
            "microsoft word": "word",
            "winword": "word",
            "word": "word",
            "google chrome": "chrome",
            "chrome browser": "chrome",
            "chrome": "chrome",
            "crow": "chrome",
            "crome": "chrome",
            "cro": "chrome",
            "chat gpt": "chrome",
            "chatgpt": "chrome",
            "gpt": "chrome",
            "charge deputy": "chrome",
            "chargeivity": "chrome",
            "vs code": "code",
            "vscode": "code",
            "visual studio code": "code",
            "code": "code",
            "calc": "calculator",
            "calculator": "calculator",
            "excel": "excel",
            "microsoft excel": "excel",
            "action excel": "excel",
            "upon xl": "excel",
            "openx": "excel",
            "powerpoint": "powerpoint",
            "microsoft powerpoint": "powerpoint",
            "edge": "msedge",
            "microsoft edge": "msedge",
            "file explorer": "explorer",
            "files": "explorer",
            "my computer": "explorer",
            "explorer": "explorer"
        }
        
        resolved = alias_mapping.get(cleaned)
        if resolved:
            return resolved

        # Data-driven fuzzy matching on single target against CANONICAL_APPLICATIONS
        fuzzy_app, matched = cls.fuzzy_match_target(cleaned)
        if matched:
            return fuzzy_app

        return cleaned

    @classmethod
    def is_valid_app_target(cls, target: str) -> bool:
        """Verifies if the resolved target matches a known canonical application, URL, or document file."""
        if not target:
            return False
        resolved = cls.resolve_target(target)
        if resolved in CANONICAL_APPLICATIONS:
            return True
        if any(resolved.endswith(ext) for ext in (".pdf", ".docx", ".txt", ".exe", ".cmd")):
            return True
        return False
