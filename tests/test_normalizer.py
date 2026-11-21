import pytest
from src.core.utils.normalizer import CommandNormalizer

def test_normalize_transcript_strips_punctuation():
    """Verifies that trailing punctuation marks are stripped cleanly."""
    assert CommandNormalizer.normalize_transcript("Open Word.") == "Open Word"
    assert CommandNormalizer.normalize_transcript("open note pad...") == "open note pad"
    assert CommandNormalizer.normalize_transcript("launch chrome, ") == "launch chrome"
    assert CommandNormalizer.normalize_transcript("Delete note.txt") == "Delete note.txt"
    assert CommandNormalizer.normalize_transcript("  close notepad? ") == "close notepad"
    assert CommandNormalizer.normalize_transcript("") == ""


def test_resolve_target_aliases():
    """Verifies that target application names are resolved to canonical names."""
    assert CommandNormalizer.resolve_target("note pad") == "notepad"
    assert CommandNormalizer.resolve_target("note pad.") == "notepad"
    assert CommandNormalizer.resolve_target("Microsoft Word") == "word"
    assert CommandNormalizer.resolve_target("winword") == "word"
    assert CommandNormalizer.resolve_target("Google Chrome") == "chrome"
    assert CommandNormalizer.resolve_target("chrome browser") == "chrome"
    assert CommandNormalizer.resolve_target("calc") == "calculator"
    assert CommandNormalizer.resolve_target("calculator.") == "calculator"
    # Unmapped apps are returned as-is
    assert CommandNormalizer.resolve_target("my_custom_app") == "my_custom_app"


def test_normalize_transcript_spelled_out_characters_and_duplicates():
    """Hostile test: Verifies that spaced single letters and duplicate stutters are collapsed cleanly."""
    assert CommandNormalizer.normalize_transcript("W O R D") == "WORD"
    assert CommandNormalizer.normalize_transcript("open open notepad notepad") == "open notepad"
    assert CommandNormalizer.normalize_transcript("which to excel") == "switch to excel"
    assert CommandNormalizer.normalize_transcript("start dictation") == "start dictating"


def test_resolve_target_phonetic_aliases():
    """Verifies that phonetic STT mishearings for Notepad resolve to canonical 'notepad'."""
    assert CommandNormalizer.resolve_target("north side") == "notepad"
    assert CommandNormalizer.resolve_target("otepad") == "notepad"
    assert CommandNormalizer.resolve_target("o-t-e-p-a-d") == "notepad"
    assert CommandNormalizer.resolve_target("load pad") == "notepad"
    assert CommandNormalizer.resolve_target("northpad") == "notepad"


def test_normalize_transcript_filters_system_echoes():
    """Verifies that TTS speaker output echoes are filtered to empty string."""
    assert CommandNormalizer.normalize_transcript("Operator system initialized.") == ""
    assert CommandNormalizer.normalize_transcript("Action failed: Could not launch calendar.") == ""
    assert CommandNormalizer.normalize_transcript("Window for calendar not found.") == ""
    assert CommandNormalizer.normalize_transcript("I'm not sure what you meant by that. Could you clarify?") == ""


def test_resolve_target_article_stripping_and_known_apps():
    """Task 1 & 3 Regression Tests: Verifies deterministic canonical application resolution and article stripping."""
    assert CommandNormalizer.resolve_target("word") == "word"
    assert CommandNormalizer.resolve_target("Word") == "word"
    assert CommandNormalizer.resolve_target("chrome") == "chrome"
    assert CommandNormalizer.resolve_target("Chrome") == "chrome"
    assert CommandNormalizer.resolve_target("the chrome") == "chrome"
    assert CommandNormalizer.resolve_target("The Chrome") == "chrome"
    assert CommandNormalizer.resolve_target("vs code") == "code"
    assert CommandNormalizer.resolve_target("VS Code") == "code"
    assert CommandNormalizer.resolve_target("visual studio code") == "code"
    assert CommandNormalizer.resolve_target("the vs code") == "code"
    assert CommandNormalizer.resolve_target("excel") == "excel"
    assert CommandNormalizer.resolve_target("action excel") == "excel"
    assert CommandNormalizer.resolve_target("chatgpt") == "chrome"
    assert CommandNormalizer.resolve_target("ChatGPT") == "chrome"
    assert CommandNormalizer.resolve_target("chat gpt") == "chrome"


def test_is_valid_app_target_rejection():
    """Task 2 Regression Tests: Rejects arbitrary unresolvable targets safely."""
    assert CommandNormalizer.is_valid_app_target("word") is True
    assert CommandNormalizer.is_valid_app_target("Word") is True
    assert CommandNormalizer.is_valid_app_target("chrome") is True
    assert CommandNormalizer.is_valid_app_target("The Chrome") is True
    assert CommandNormalizer.is_valid_app_target("VS Code") is True
    assert CommandNormalizer.is_valid_app_target("excel") is True
    assert CommandNormalizer.is_valid_app_target("guide.pdf") is True
    assert CommandNormalizer.is_valid_app_target("notes.docx") is True

    # Rejection of unknown / arbitrary strings
    assert CommandNormalizer.is_valid_app_target("on") is False
    assert CommandNormalizer.is_valid_app_target("xyzabc") is False
    assert CommandNormalizer.is_valid_app_target("random_gibberish") is False
    assert CommandNormalizer.is_valid_app_target("") is False

