from pathlib import Path
import pytest


def test_mock_tests_removed_or_not_using_pure_string_mocks():
    """Item 7: Mock-based 30 noise clips, stop-latency, and 30-off-topic tests must be removed."""
    repo_root = Path(__file__).parent.parent

    # Check test_noise_rejection_and_stop_latency.py
    noise_file = repo_root / "tests" / "test_noise_rejection_and_stop_latency.py"
    if noise_file.exists():
        content = noise_file.read_text(encoding="utf-8")
        assert "def test_30_non_command_noise_clips_rejection" not in content, (
            "Mock-based 30 noise clips test still present in test_noise_rejection_and_stop_latency.py"
        )
        assert "def test_stop_latency_under_300ms" not in content, (
            "Mock-based stop latency test still present in test_noise_rejection_and_stop_latency.py"
        )

    # Check test_llamacpp_provider.py
    llm_file = repo_root / "tests" / "test_llamacpp_provider.py"
    if llm_file.exists():
        content = llm_file.read_text(encoding="utf-8")
        assert "def test_llamacpp_provider_30_off_topic_phrases_return_unknown" not in content, (
            "Mock-based 30-off-topic test still present in test_llamacpp_provider.py"
        )


def test_from_typing_import_any_fixed():
    """Item 7: Fix 'from typing import Any' in src/main.py."""
    repo_root = Path(__file__).parent.parent
    main_file = repo_root / "src" / "main.py"
    content = main_file.read_text(encoding="utf-8")

    assert "from typing import Any" not in content, "from typing import Any still present in src/main.py"
