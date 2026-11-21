param(
    [switch]$HardwareGate,
    [switch]$HermeticCI,
    [string]$HardwareLogsPath = "logs/session.jsonl"
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "STARTING VOICE OPERATOR V1 RELEASE GATE" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

function Run-GateStep {
    param(
        [string]$StepName,
        [string]$Command
    )
    Write-Host "`n>>> Running Gate: $StepName..." -ForegroundColor Yellow
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`n[RELEASE GATE FAILED] $StepName exited with error code $LASTEXITCODE!" -ForegroundColor Red
        exit $LASTEXITCODE
    }
    Write-Host ">>> [PASS] $StepName completed successfully." -ForegroundColor Green
}

# -----------------------------------------------------------------------------
# Mode 1: Manual Hardware Gate (-HardwareGate)
# -----------------------------------------------------------------------------
if ($HardwareGate) {
    Write-Host "`n=== MANUAL HARDWARE VERIFICATION GATE ===" -ForegroundColor Cyan

    if (-not (Test-Path $HardwareLogsPath)) {
        Write-Host "`n[HARDWARE GATE FAILED] Required hardware log file '$HardwareLogsPath' was not found." -ForegroundColor Red
        Write-Host "Never printing 'verified': Real hardware verification logs do not exist." -ForegroundColor Red
        exit 1
    }

    $hardwareVerified = $false
    try {
        $lines = Get-Content -Path $HardwareLogsPath
        foreach ($line in $lines) {
            if (-not [string]::IsNullOrWhiteSpace($line)) {
                $entry = $line | ConvertFrom-Json
                # Check for non-default real hardware device entry with genuine recorded RMS
                if ($entry.device -and $entry.device -ne "default" -and [double]$entry.rms -gt 0.0) {
                    $hardwareVerified = $true
                    break
                }
            }
        }
    } catch {
        Write-Host "`n[HARDWARE GATE ERROR] Failed to parse hardware log file '$HardwareLogsPath': $_" -ForegroundColor Red
        exit 1
    }

    if (-not $hardwareVerified) {
        Write-Host "`n[HARDWARE GATE FAILED] No genuine hardware execution entries (device != default, rms > 0) found in '$HardwareLogsPath'." -ForegroundColor Red
        Write-Host "Never printing 'verified': Hardware logs lack genuine audio recording entries." -ForegroundColor Red
        exit 1
    }

    Write-Host "`n================================================================================" -ForegroundColor Green
    Write-Host "[HARDWARE GATE PASSED] Genuine hardware logs verified from '$HardwareLogsPath'!" -ForegroundColor Green
    Write-Host "Voice Operator v1 is verified for offline deployment." -ForegroundColor Green
    Write-Host "================================================================================" -ForegroundColor Green
    exit 0
}

# -----------------------------------------------------------------------------
# Mode 2: Hermetic CI Gates (Runs across all environments without hardware)
# -----------------------------------------------------------------------------
Write-Host "`n=== HERMETIC CI GATES ===" -ForegroundColor Cyan

# 1. Production Wiring Gate (Defaults to production, --mock validation)
Run-GateStep -StepName "Production Wiring & Default Validation" -Command ".venv\Scripts\python.exe -m pytest tests/test_production_wiring.py -v"

# 2. Resampling, Anti-Aliasing, and Audio Stream Enhancements
Run-GateStep -StepName "Audio Source, Resampling & Stream Persistence" -Command ".venv\Scripts\python.exe -m pytest tests/test_audio_source.py tests/test_audio_stream_enhancements.py -v"

# 3. Silero VAD Hysteresis & Hard Cap Unit Tests
Run-GateStep -StepName "Silero VAD Dual-Threshold State Machine" -Command ".venv\Scripts\python.exe -m pytest tests/test_silero_vad.py -v"

# 4. Whisper STT Hallucination Gate & Task=Transcribe Tests
Run-GateStep -StepName "Whisper STT Hallucination & Prompt Filtering" -Command ".venv\Scripts\python.exe -m pytest tests/test_whisper_stt.py -v"

# 5. Normalizer Rapidfuzz Matching, Hindi Lexicon & Crow Alias
Run-GateStep -StepName "Normalizer Matching, Hindi Lexicon & Phonetic Alias" -Command ".venv\Scripts\python.exe -m pytest tests/test_normalizer.py tests/test_evidence_and_alias.py -v"

# 6. LLM Rules Intent Parser & Prompt Fallbacks
Run-GateStep -StepName "LLM Rules & Intent Parsing" -Command ".venv\Scripts\python.exe -m pytest tests/test_llamacpp_provider.py -v"

# 7. Attention Policy, State Machine & Dictation Mode Tests
Run-GateStep -StepName "State Machine, Attention Policy & Dictation" -Command ".venv\Scripts\python.exe -m pytest tests/test_state_machine.py -v"

# 8. Confirmation State Machine Hardening
Run-GateStep -StepName "Confirmations Hardening (ModeManager Only)" -Command ".venv\Scripts\python.exe -m pytest tests/test_confirmations.py -v"

# 9. Stop Path & Real Measured Latency
Run-GateStep -StepName "Stop Path & Real Latency Measurement" -Command ".venv\Scripts\python.exe -m pytest tests/test_stop_path.py -v"

# 10. Window Control Hardening & Scoped Dialogs
Run-GateStep -StepName "Window Control Hardening & Scoped Dialogs" -Command ".venv\Scripts\python.exe -m pytest tests/test_window_control_hardening.py -v"

# 11. SAFE-7 Spoken Cues on Dropped Utterances
Run-GateStep -StepName "SAFE-7 Spoken Cues on Dropped Utterances" -Command ".venv\Scripts\python.exe -m pytest tests/test_safe7_and_whisper_filter.py -v"

# 12. Soak Test Verification (Memory Growth < 200 MB, Zero Thread Leaks)
Run-GateStep -StepName "Stability & Memory Leak Soak Check" -Command ".venv\Scripts\python.exe scripts/soak_test.py --seconds 10"

Write-Host "`n================================================================================" -ForegroundColor Green
Write-Host "[CI GATES PASSED] All hermetic CI gates passed cleanly." -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green
exit 0
