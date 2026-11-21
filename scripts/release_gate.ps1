# Release Gate for Voice Operator v1
# Exits with non-zero code on any gate failure.

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "STARTING VOICE OPERATOR V1 RELEASE GATE VERIFICATION" -ForegroundColor Cyan
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

# 1. Production Wiring Gate (No mocks/stubs, startup hardware self-check)
Run-GateStep -StepName "Production Wiring & Startup Self-Check" -Command ".venv\Scripts\pytest tests/test_production_wiring.py -v"

# 2. Resampling & Anti-Aliasing Unit Tests
Run-GateStep -StepName "Resampling Anti-Aliasing & Audio Source" -Command ".venv\Scripts\pytest tests/test_audio_source.py -v"

# 3. Silero VAD Hysteresis & Hard Cap Unit Tests
Run-GateStep -StepName "Silero VAD Dual-Threshold State Machine" -Command ".venv\Scripts\pytest tests/test_silero_vad.py -v"

# 4. Whisper STT Hallucination Gate & Task=Transcribe Tests
Run-GateStep -StepName "Whisper STT Hallucination Gate & Language Detection" -Command ".venv\Scripts\pytest tests/test_whisper_stt.py -v"

# 5. Normalizer Rapidfuzz Fuzzy Matching & Hindi Lexicon Tests
Run-GateStep -StepName "Normalizer Rapidfuzz Matching & Hindi Lexicon" -Command ".venv\Scripts\pytest tests/test_normalizer.py -v"

# 6. LLM Intent GBNF Grammar & 30 Off-Topic Phrases Rejection
Run-GateStep -StepName "LLM Provider 30 Off-Topic Rejection Gate" -Command ".venv\Scripts\pytest tests/test_llamacpp_provider.py -v"

# 7. Attention Policy, State Machine & Dictation Mode Tests
Run-GateStep -StepName "State Machine, Attention Policy & Dictation" -Command ".venv\Scripts\pytest tests/test_state_machine.py -v"

# 8. Non-Command Noise Clips & Stop Latency (< 300 ms) Gate
Run-GateStep -StepName "30 Non-Command Noise Rejection & Stop Latency" -Command ".venv\Scripts\pytest tests/test_noise_rejection_and_stop_latency.py -v"

# 9. Real Local Audio Fixtures Replay Evaluation (>= 90% Intent Accuracy)
Run-GateStep -StepName "Audio Fixtures Real STT Replay Evaluation" -Command ".venv\Scripts\pytest tests/audio/test_replay.py -v"

# 10. Soak Test Verification (Memory Growth < 200 MB, Zero Thread Leaks)
Run-GateStep -StepName "Stability & Memory Leak Soak Check" -Command ".venv\Scripts\python scripts/soak_test.py --seconds 10"

Write-Host "`n================================================================================" -ForegroundColor Green
Write-Host "[RELEASE GATE PASSED] All 10 release verification gates passed cleanly!" -ForegroundColor Green
Write-Host "Voice Operator v1 is verified for offline deployment." -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green
exit 0
