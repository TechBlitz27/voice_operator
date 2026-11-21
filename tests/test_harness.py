from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_operator(*commands: str, timeout: float = 15.0) -> str:
    """Run the public mock application with scripted user input."""
    payload = "\n".join(commands) + "\n"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--mock"],
        input=payload,
        text=True,
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=timeout,
    )

    output = (result.stdout or "") + (result.stderr or "")

    assert result.returncode == 0, (
        f"src.main exited with code {result.returncode}\n\n"
        f"STDOUT:\n{result.stdout}\n\n"
        f"STDERR:\n{result.stderr}"
    )

    return output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_contains(output: str, *expected: str) -> None:
    """Assert that all expected fragments occur in application output."""
    for fragment in expected:
        assert fragment.lower() in output.lower(), (
            f"Expected output fragment not found: {fragment!r}\n\n"
            f"Actual output:\n{output}"
        )


# ---------------------------------------------------------------------------
# Startup / basic command routing
# ---------------------------------------------------------------------------

def test_application_starts_and_initializes() -> None:
    output = run_operator("system initialized. Ready.")

    assert_contains(
        output,
        "AI Task Operator for Accessibility",
        "Starting voice accessibility operator loop",
        "Operator",
    )


def test_open_application() -> None:
    output = run_operator("open notepad")

    assert_contains(
        output,
        "Executing action: open_app",
        "target: 'notepad'",
        "Opened notepad",
    )


def test_switch_application() -> None:
    output = run_operator("switch to chrome")

    assert_contains(
        output,
        "Executing action: switch_app",
        "target: 'chrome'",
        "Switched to chrome",
    )


def test_close_application() -> None:
    output = run_operator("close word")

    assert_contains(
        output,
        "Executing action: close_app",
        "target: 'word'",
        "Closed word",
    )


def test_ambiguous_command_requests_clarification() -> None:
    output = run_operator("do something random")

    assert_contains(
        output,
        "I'm not sure what",
        "Could you clarify",
    )


# ---------------------------------------------------------------------------
# Safety confirmation
# ---------------------------------------------------------------------------

def test_delete_requires_confirmation() -> None:
    output = run_operator("delete note.txt")

    assert_contains(
        output,
        "Are you sure",
        "say yes to confirm",
    )

    # Critical safety assertion: merely issuing the dangerous command must
    # not execute the destructive action.
    assert "Executing action: delete_file" not in output


def test_delete_rejected_does_not_execute() -> None:
    output = run_operator(
        "delete note.txt",
        "no",
    )

    assert_contains(
        output,
        "User canceled/rejected action 'delete_file'",
        "Action canceled",
    )

    assert "Executing action: delete_file" not in output


def test_delete_confirmed_executes() -> None:
    output = run_operator(
        "delete word.docx",
        "yes",
    )

    assert_contains(
        output,
        "User confirmed action 'delete_file'",
        "Executing action: delete_file",
        "Deleted file word.docx",
    )


def test_confirmation_accepts_only_explicit_yes_for_execution() -> None:
    output = run_operator(
        "delete note.txt",
        "maybe",
    )

    # A non-affirmative answer must not authorize execution.
    assert "Executing action: delete_file" not in output

    # The implementation may classify this as cancellation or clarification;
    # either is safe. It must never execute the destructive action.
    assert (
        "Action canceled" in output
        or "clarify" in output.lower()
        or "yes" in output.lower()
    )


# ---------------------------------------------------------------------------
# Unsaved changes / escalation
# ---------------------------------------------------------------------------

def test_unsaved_close_escalates_to_confirmation() -> None:
    output = run_operator("close unsaved_word")

    assert_contains(
        output,
        "Simulating unsaved changes dialog detection",
        "Warning: Dialog window detected",
        "force close",
        "say yes to confirm",
    )

    assert "Closed unsaved_word" not in output


def test_unsaved_close_rejected_does_not_force_close() -> None:
    output = run_operator(
        "close unsaved_word",
        "no",
    )

    assert_contains(
        output,
        "User canceled/rejected action 'close_app'",
        "Action canceled",
    )

    # The application may log the attempted close, but must not report a
    # successful close after the confirmation is rejected.
    assert "Closed unsaved_word" not in output


def test_unsaved_close_accepts_explicit_yes() -> None:
    output = run_operator(
        "close unsaved_word",
        "yes",
    )

    assert_contains(
        output,
        "Warning: Dialog window detected",
        "User confirmed action 'close_app'",
    )


def test_natural_rejection_does_not_authorize_force_close() -> None:
    output = run_operator(
        "close unsaved_word",
        "no first save it than close",
    )

    # This is intentionally a safety test. The current confirmation gate may
    # treat the utterance as a rejection/ambiguous response, but it must never
    # interpret it as authorization to force-close.
    assert "Closed unsaved_word" not in output


# ---------------------------------------------------------------------------
# Dictation mode
# ---------------------------------------------------------------------------

def test_dictation_mode_starts() -> None:
    output = run_operator("start dictating")

    assert_contains(
        output,
        "Starting dictation mode",
    )


def test_dictation_bypasses_llm_and_types_raw_text() -> None:
    dictated_text = "hello this is exact user text"

    output = run_operator(
        "start dictating",
        dictated_text,
    )

    assert_contains(
        output,
        "Starting dictation mode",
        f"Typing text into active app",
        dictated_text,
    )

    # The transcript must not become an LLM-derived application command.
    assert "I'm not sure what" not in output


def test_dictation_preserves_command_like_text_as_text() -> None:
    output = run_operator(
        "start dictating",
        "open notepad",
    )

    # While in Dictation Mode, "open notepad" is user text, not a command.
    assert_contains(
        output,
        "Typing text into active app",
        "open notepad",
    )

    assert "Executing action: open_app" not in output


def test_stop_dictating_returns_to_command_mode() -> None:
    output = run_operator(
        "start dictating",
        "hello from dictation",
        "stop dictating",
        "open notepad",
    )

    assert_contains(
        output,
        "Starting dictation mode",
        "hello from dictation",
        "Executing action: open_app",
        "Opened notepad",
    )


# ---------------------------------------------------------------------------
# Reading mode
# ---------------------------------------------------------------------------

def test_read_document_enters_reading_mode() -> None:
    output = run_operator("read guide.pdf")

    assert_contains(
        output,
        "guide.pdf",
    )

    # The mock should identify this as a reading request rather than typing
    # it as ordinary dictation.
    assert "Typing text into active app" not in output


@pytest.mark.parametrize(
    "keyword",
    ["pause", "resume", "next", "repeat", "stop"],
)
def test_reading_control_keyword_is_handled(keyword: str) -> None:
    output = run_operator(
        "read guide.pdf",
        keyword,
    )

    # We intentionally check that the keyword is not blindly typed into the
    # active application. Exact spoken wording can vary by implementation.
    assert "Typing text into active app" not in output


def test_reading_mode_does_not_treat_normal_text_as_dictation() -> None:
    output = run_operator(
        "read guide.pdf",
        "hello",
    )

    assert "Typing text into active app" not in output


# ---------------------------------------------------------------------------
# Emergency stop
# ---------------------------------------------------------------------------

def test_emergency_stop_command_is_recognized() -> None:
    output = run_operator("stop")

    assert_contains(
        output,
        "stop",
    )


def test_emergency_stop_is_not_executed_as_an_application_action() -> None:
    output = run_operator("stop")

    assert "Executing action: open_app" not in output
    assert "Executing action: delete_file" not in output
    assert "Executing action: close_app" not in output


# ---------------------------------------------------------------------------
# Undo / recovery
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    ["undo", "undo last action"],
)
def test_undo_command_is_recognized(command: str) -> None:
    output = run_operator(command)

    assert_contains(output, "undo")


# ---------------------------------------------------------------------------
# High-risk second action
# ---------------------------------------------------------------------------

def test_send_email_requires_confirmation() -> None:
    output = run_operator("send email to john@example.com")

    assert_contains(
        output,
        "Are you sure",
        "yes",
    )

    assert "Executing action: send_email" not in output


def test_send_email_rejected() -> None:
    output = run_operator(
        "send email to john@example.com",
        "no",
    )

    assert_contains(
        output,
        "Action canceled",
    )

    assert "Executing action: send_email" not in output


def test_send_email_confirmed() -> None:
    output = run_operator(
        "send email to john@example.com",
        "yes",
    )

    assert_contains(
        output,
        "Executing action: send_email",
    )


# ---------------------------------------------------------------------------
# End-to-end behavioral flows
# ---------------------------------------------------------------------------

def test_complete_safe_user_flow() -> None:
    output = run_operator(
        "open notepad",
        "switch to chrome",
        "start dictating",
        "hello this is a test",
        "stop dictating",
        "read guide.pdf",
    )

    assert_contains(
        output,
        "Opened notepad",
        "Switched to chrome",
        "Starting dictation mode",
        "hello this is a test",
        "guide.pdf",
    )


def test_dangerous_flow_cannot_bypass_confirmation_with_multiple_commands() -> None:
    output = run_operator(
        "delete note.txt",
        "hello",
    )

    # "hello" is not permission.
    assert "Executing action: delete_file" not in output


# ---------------------------------------------------------------------------
# Regression test for the previously observed mock parsing issue
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "close 1.word",
        "close Word",
        "close Microsoft Word",
    ],
)
def test_close_target_is_not_truncated(command: str) -> None:
    """
    Regression guard for the observed:
        "close 1.word" -> target "1"

    The mock parser should preserve the meaningful target. If the current
    implementation still truncates it, this test intentionally fails and
    identifies the defect.
    """
    output = run_operator(command)

    assert "Executing action: close_app" in output

    if command == "close 1.word":
        assert "target: '1.word'" in output


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

def test_no_delete_execution_without_yes() -> None:
    for response in ("no", "maybe", "cancel", "I don't want that"):
        output = run_operator(
            "delete note.txt",
            response,
        )

        assert "Executing action: delete_file" not in output


def test_no_unsaved_force_close_without_yes() -> None:
    for response in ("no", "maybe", "cancel"):
        output = run_operator(
            "close unsaved_word",
            response,
        )

        assert "Closed unsaved_word" not in output


def test_hostile_phonetic_and_dictation_recovery_flow() -> None:
    """Hostile test: Verifies end-to-end pipeline handles phonetic mishearings, dictation mode, undo, and clean exit."""
    output = run_operator(
        "which to chrome",
        "start dictation",
        "this is dictated test text",
        "undo",
        "stop dictating",
        "exit voice operator"
    )

    assert_contains(
        output,
        "Switched to chrome",
        "Starting dictation mode",
        "this is dictated test text",
        "Exiting voice operator",
    )
