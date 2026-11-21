import glob
import inspect
import os
import re
import sys
import time
from typing import List, Optional, Set
import numpy as np

from src.core.interfaces.speech import SpeechRecognizer


def _speak_stt_error(msg: str) -> None:
    """Speaks critical STT initialization error using Windows SAPI (offline)."""
    try:
        import win32com.client
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        speaker.Speak(msg, 1)  # 1 = SVSFlagsAsync
    except Exception:
        pass


def get_start_menu_apps() -> List[str]:
    """Discovers installed desktop application names from Windows Start Menu shortcuts."""
    app_names: Set[str] = {
        "Chrome", "Word", "Excel", "Notepad", "Calculator", "Visual Studio Code",
        "Edge", "File Explorer", "PowerPoint"
    }
    paths = [
        os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("APPDATA", r"C:\Users\Default\AppData\Roaming"), r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for p in paths:
        if os.path.exists(p):
            for lnk in glob.glob(os.path.join(p, "**", "*.lnk"), recursive=True):
                base = os.path.splitext(os.path.basename(lnk))[0]
                # Filter out uninstaller or help shortcuts
                if not re.search(r"uninstall|help|manual|readme|website", base, re.I):
                    app_names.add(base.strip())
    return sorted(list(app_names))


COMMAND_PROMPT_PREFIX = "Open Chrome. Close Word. Switch to Excel. Start dictating. Stop dictating. Read this document. Stop. "

HALLUCINATION_BLACKLIST: Set[str] = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching.",
    "thank you for watching", "thank you for watching.", "you", "you.",
    "bye", "bye.", "subscribe", "please subscribe", "subtitles by",
    "amara.org", "watching", "the end", "the end."
}


class WhisperSpeechRecognizer(SpeechRecognizer):
    """Production Speech Recognizer wrapping faster-whisper for offline CTranslate2 execution.
    Configured for Indian-accented English and Hindi command recognition.
    """

    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        language: Optional[str] = "en",
        languages: Optional[List[str]] = None,
        mode: str = "command"
    ):
        self.model_size = model_size
        self.device = device
        self.language = language or "en"
        self.languages = languages if languages is not None else ["en", "hi"]
        self.mode = mode  # "command" or "dictation"

        self.last_language = self.language
        self.last_language_probability = 1.0
        self.last_avg_logprob = 0.0
        self.last_no_speech_prob = 0.0
        self._model = None
        self._initialized = False

        # Build dynamic command initial prompt biased toward commands and installed apps
        apps = get_start_menu_apps()
        self._command_initial_prompt = COMMAND_PROMPT_PREFIX + ", ".join(apps[:30])
        self._hotwords = "open, close, switch, word, excel, chrome, notepad, dictating, document, stop"

        # Check faster_whisper hotwords support
        try:
            from faster_whisper import WhisperModel
            sig = inspect.signature(WhisperModel.transcribe)
            self._supports_hotwords = "hotwords" in sig.parameters
        except Exception:
            self._supports_hotwords = False

        # Load local Whisper model
        try:
            from faster_whisper import WhisperModel

            # Look for model in models/whisper-<model_size>
            model_path = os.path.join("models", f"whisper-{model_size}")
            if not os.path.exists(model_path):
                # Fallback to base if small is missing, or fail
                fallback_base = os.path.join("models", "whisper-base")
                if os.path.exists(fallback_base) and model_size != "base":
                    print(f"[STT] WARNING: Model '{model_path}' not found, falling back to '{fallback_base}'.")
                    model_path = fallback_base
                else:
                    err = f"Whisper STT model missing at '{model_path}'. Local model must be installed for offline operation."
                    print(f"[STT] CRITICAL ERROR: {err}", file=sys.stderr)
                    _speak_stt_error("Error: Speech recognition model is missing.")
                    raise FileNotFoundError(err)

            self._model = WhisperModel(model_path, device=self.device, compute_type="int8")
            self._initialized = True
            print(f"[STT] CTranslate2 Whisper model loaded successfully from '{model_path}'.")
        except Exception as e:
            if isinstance(e, FileNotFoundError):
                raise
            err = f"Failed to initialize faster-whisper STT: {e}"
            print(f"[STT] CRITICAL ERROR: {err}", file=sys.stderr)
            _speak_stt_error("Error: Failed to initialize speech recognizer.")
            raise RuntimeError(err) from e

    def set_mode(self, mode: str) -> None:
        """Sets STT mode: 'command' or 'dictation'."""
        self.mode = mode

    def transcribe(self, audio_data: bytes, mode: Optional[str] = None) -> str:
        """Transcribes raw 16 kHz mono audio buffer into text.
        Never translates: always uses task='transcribe'.
        Applies language selection, command bias, and strict hallucination gate.
        """
        if not audio_data:
            return ""

        if not self._initialized or not self._model:
            err = "Whisper speech recognizer is not initialized."
            print(f"[STT] CRITICAL ERROR: {err}", file=sys.stderr)
            _speak_stt_error("Error: Speech recognition engine is not ready.")
            raise RuntimeError(err)

        current_mode = mode if mode is not None else self.mode
        t_start = time.time()

        try:
            # Decode audio buffer to float32 normalized [-1.0, 1.0]
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            # Language detection: detect only on first 3s (48000 samples)
            target_lang = self.language
            if self.languages and len(audio_array) > 0:
                first_3s = audio_array[: 3 * 16000]
                try:
                    detected_lang, prob, _ = self._model.detect_language(first_3s)
                    self.last_language_probability = float(prob)
                    if prob >= 0.7 and detected_lang in self.languages:
                        target_lang = detected_lang
                    else:
                        target_lang = "en"
                    self.last_language = target_lang
                except Exception as lang_err:
                    print(f"[STT] Language detection error: {lang_err}, defaulting to 'en'")
                    target_lang = "en"
                    self.last_language = "en"

            # Biasing and initial prompt
            transcribe_kwargs = {
                "task": "transcribe",  # Never translate
                "language": target_lang,
                "beam_size": 5,
                "condition_on_previous_text": False,
                "no_speech_threshold": 0.6,
                "log_prob_threshold": -1.0,
                "compression_ratio_threshold": 2.4,
                "vad_filter": False,  # Downstream of our Silero VAD
            }

            if current_mode == "command":
                transcribe_kwargs["initial_prompt"] = self._command_initial_prompt
                if self._supports_hotwords:
                    transcribe_kwargs["hotwords"] = self._hotwords
            else:
                # Dictation mode: no command bias
                transcribe_kwargs["initial_prompt"] = None

            # Execute faster-whisper transcription
            segments_gen, info = self._model.transcribe(audio_array, **transcribe_kwargs)
            segments = list(segments_gen)

            # Record metrics
            if info is not None:
                self.last_language = getattr(info, "language", target_lang)
                self.last_language_probability = float(getattr(info, "language_probability", 1.0))

            avg_logprobs = [s.avg_logprob for s in segments if hasattr(s, "avg_logprob")]
            no_speech_probs = [s.no_speech_prob for s in segments if hasattr(s, "no_speech_prob")]

            self.last_avg_logprob = float(np.mean(avg_logprobs)) if avg_logprobs else 0.0
            self.last_no_speech_prob = float(np.mean(no_speech_probs)) if no_speech_probs else 0.0

            raw_texts = [segment.text.strip() for segment in segments if segment.text.strip()]
            
            # Collapse repeated hallucination loops
            unique_texts = []
            for t in raw_texts:
                if not unique_texts or t.lower() != unique_texts[-1].lower():
                    unique_texts.append(t)
            transcription = " ".join(unique_texts).strip()

            # Filter Whisper output equal to the initial_prompt
            clean_transcription = transcription.strip().lower()
            clean_prompt = self._command_initial_prompt.strip().lower()
            clean_prefix = COMMAND_PROMPT_PREFIX.strip().lower()
            if clean_transcription and (clean_transcription == clean_prompt or clean_transcription == clean_prefix):
                print(f"[STT] Filtered Whisper output equal to initial_prompt: '{transcription}'")
                return ""

            # Hallucination Gate
            # Gate 1: Check no_speech_prob > 0.6 and avg_logprob < -1.0
            if self.last_no_speech_prob > 0.6:
                print(f"[STT] Hallucination gate: dropped transcript '{transcription}' (no_speech_prob: {self.last_no_speech_prob:.2f} > 0.6)")
                return ""
            if self.last_avg_logprob < -1.0:
                print(f"[STT] Hallucination gate: dropped transcript '{transcription}' (avg_logprob: {self.last_avg_logprob:.2f} < -1.0)")
                return ""

            # Gate 2: Command-mode blacklist and punctuation-only check
            if current_mode == "command":
                clean_lower = transcription.lower().strip()
                if clean_lower in HALLUCINATION_BLACKLIST:
                    print(f"[STT] Hallucination gate: dropped blacklisted command '{transcription}'")
                    return ""
                # Strip leading/trailing punctuation
                clean_no_punct = re.sub(r"^[\s\.\,\?\!\;\:\—\-]+|[\s\.\,\?\!\;\:\—\-]+$", "", transcription).strip()
                if not clean_no_punct or re.match(r"^[\s\.\,\?\!\;\:\—\-]+$", transcription):
                    print(f"[STT] Hallucination gate: dropped empty/punctuation-only transcript '{transcription}'")
                    return ""

            duration = time.time() - t_start
            print(f"[STT] Transcribed text: '{transcription}' (lang: {self.last_language}, prob: {self.last_language_probability:.2f}, avg_logprob: {self.last_avg_logprob:.2f}, latency: {duration:.3f}s)")
            return transcription

        except Exception as e:
            print(f"[STT] Error during transcription: {e}", file=sys.stderr)
            return ""
