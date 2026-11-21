import json
import subprocess
from pathlib import Path
import pytest


def test_ci_gate_hermetic_mode_never_prints_verified():
    """Item 9: Hermetic CI release gate must never print 'verified'."""
    repo_root = Path(__file__).parent.parent
    gate_script = repo_root / "scripts" / "release_gate.ps1"

    content = gate_script.read_text(encoding="utf-8")
    assert "$HardwareGate" in content
    assert "Never printing 'verified'" in content
    assert "[CI GATES PASSED]" in content
    # In hermetic section, 'verified for offline deployment' must NOT appear
    ci_section = content.split("=== HERMETIC CI GATES ===")[-1]
    assert "is verified for offline deployment" not in ci_section


def test_hardware_gate_fails_when_hardware_logs_missing(tmp_path):
    """Item 9: Hardware gate must fail and never print verified if hardware logs are missing."""
    repo_root = Path(__file__).parent.parent
    gate_script = repo_root / "scripts" / "release_gate.ps1"

    non_existent_log = tmp_path / "non_existent_hardware_log.jsonl"
    cmd = [
        "powershell",
        "-ExecutionPolicy", "Bypass",
        "-File", str(gate_script),
        "-HardwareGate",
        "-HardwareLogsPath", str(non_existent_log)
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)

    assert result.returncode != 0, "Hardware gate should fail when hardware logs are missing!"
    combined = (result.stdout + result.stderr).lower()
    assert "never printing 'verified'" in combined or "was not found" in combined


def test_hardware_gate_fails_when_logs_lack_real_audio(tmp_path):
    """Item 9: Hardware gate must fail if logs only have default/simulated entries."""
    repo_root = Path(__file__).parent.parent
    gate_script = repo_root / "scripts" / "release_gate.ps1"

    fake_log = tmp_path / "fake_log.jsonl"
    fake_log.write_text(
        json.dumps({"device": "default", "rms": 0.0, "raw_text": "open notepad"}) + "\n",
        encoding="utf-8"
    )

    cmd = [
        "powershell",
        "-ExecutionPolicy", "Bypass",
        "-File", str(gate_script),
        "-HardwareGate",
        "-HardwareLogsPath", str(fake_log)
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)

    assert result.returncode != 0, "Hardware gate must reject logs without real hardware entries!"
    combined = (result.stdout + result.stderr).lower()
    assert "never printing 'verified'" in combined


def test_hardware_gate_passes_when_real_hardware_logs_exist(tmp_path):
    """Item 9: Hardware gate passes and prints verified when genuine hardware logs exist."""
    repo_root = Path(__file__).parent.parent
    gate_script = repo_root / "scripts" / "release_gate.ps1"

    real_hw_log = tmp_path / "real_hardware_log.jsonl"
    real_hw_log.write_text(
        json.dumps({
            "timestamp": "2026-11-21T18:00:00+00:00",
            "device": "18",
            "rms": 2949.4,
            "vad_prob": 1.0,
            "duration": 2.45,
            "raw_text": "open notepad",
            "intent": "open_app"
        }) + "\n",
        encoding="utf-8"
    )

    cmd = [
        "powershell",
        "-ExecutionPolicy", "Bypass",
        "-File", str(gate_script),
        "-HardwareGate",
        "-HardwareLogsPath", str(real_hw_log)
    ]
    result = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)

    assert result.returncode == 0, f"Hardware gate failed on valid hardware log: {result.stderr}"
    assert "voice operator v1 is verified for offline deployment" in result.stdout.lower()
