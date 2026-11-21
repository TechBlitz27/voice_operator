from pathlib import Path
import pytest

from src.core.utils.normalizer import CommandNormalizer


def test_hardware_matrix_deleted_and_baseline_table_from_session_logs():
    """Item 8: HARDWARE_MATRIX.md must be deleted; BASELINE.md hardware table regenerated from logs/session.jsonl."""
    repo_root = Path(__file__).parent.parent

    # 1. HARDWARE_MATRIX.md must be deleted
    hw_matrix_file = repo_root / "docs" / "HARDWARE_MATRIX.md"
    assert not hw_matrix_file.exists(), "docs/HARDWARE_MATRIX.md must be deleted!"

    # 2. BASELINE.md must not contain the old synthetic hardware table
    baseline_file = repo_root / "docs" / "BASELINE.md"
    content = baseline_file.read_text(encoding="utf-8")
    assert "A2DP BT Speaker" not in content, "Old synthetic hardware table still present in BASELINE.md"
    assert "3.5mm CTIA analog headset" not in content, "Old synthetic hardware table still present in BASELINE.md"
    assert "session.jsonl" in content, "BASELINE.md must document regenerated evidence from logs/session.jsonl"


def test_crow_resolves_to_chrome_alias():
    """Item 8: 'Crow' / 'crow' must resolve to 'chrome' from the installed-app list."""
    # Test resolve_target
    assert CommandNormalizer.resolve_target("crow") == "chrome"
    assert CommandNormalizer.resolve_target("Crow") == "chrome"

    # Test full transcript normalization
    norm_close = CommandNormalizer.normalize_transcript("close crow")
    assert "chrome" in norm_close, f"Expected 'chrome' in normalized transcript, got '{norm_close}'"

    norm_switch = CommandNormalizer.normalize_transcript("switch to crow")
    assert "chrome" in norm_switch, f"Expected 'chrome' in normalized transcript, got '{norm_switch}'"
