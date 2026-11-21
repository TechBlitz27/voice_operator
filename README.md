# AI Task Operator for Accessibility (Windows Offline Accessibility Layer)

An offline, voice-operated accessibility layer for Windows that enables blind or low-vision users to complete desktop tasks using natural, conversational speech rather than rigid screen-reader commands or memorized keyboard shortcuts.

The system uses local machine learning models (Silero-VAD, Whisper STT, and Llama/Qwen LLMs) combined with native Windows UI Automation to parse, validate, and execute desktop commands safely and entirely offline.

---

## Key Features

1. **Three-Way State Machine**:
   * **Command Mode**: Natural language requests parsed by a local LLM (e.g., *"Open Notepad"*, *"Delete note.txt"*).
   * **Dictation Mode**: Bypasses the LLM entirely to type speech literally into the active field, supporting basic editing commands (e.g., *"delete last word"*).
   * **Reading Mode**: Low-latency document playback (PDF/DOCX) using keyword controls (e.g., *"pause"*, *"resume"*, *"stop"*, *"repeat"*).
2. **Safety Confirmation Gates**:
   * Irreversible actions (like deleting files or sending emails) prompt for an explicit spoken **"Yes"** before execution.
   * Attempting to close applications with unsaved changes detects Win32 dialog blocks and escalates to a force-close confirmation flow.
3. **Interruptible Voice Control**:
   * Spoken **"stop"** cancels pending confirmation and active synthesis after transcription; SAPI cancellation is handled by its dedicated COM worker.

---

## Project Structure

```text
src/
  core/
    interfaces/         # Abstract Base Classes (enforces decoupling boundary)
    models/             # Pydantic schemas (LLMIntent, ExecutorAction)
    state_machine/      # StateMachine mode manager and safety logic
  adapters/             # Concrete third-party adapters (Windows APIs, ML runtimes)
    mocks/              # Regex & simulated terminal mocks for fast testing
    sapi_tts.py         # Windows SAPI5 Speech Synthesizer (pyttsx3)
    windows_control.py  # Window tracking, typing, Outlook COM (pywinauto/pywin32)
    pdf_reader.py       # PDF extraction (pdfplumber)
    docx_reader.py      # Word document extraction (python-docx)
    sounddevice_audio.py# Microphone frame capture (sounddevice)
    silero_vad.py       # Silence/speech detection (silero-vad ONNX/RMS)
    whisper_stt.py      # Local Speech-to-Text (faster-whisper)
    llamacpp_provider.py# Grammar-constrained JSON LLM parser (llama-cpp-python)
  orchestrator.py       # Composition root managing the main loop and safety gates
  main.py               # Main entry point parsing arguments
tests/                  # Complete unit, integration, and adapter test suites
```

---

## Setup & Installation

### Prerequisites
* Windows OS (required for native SAPI5, Outlook COM, and Windows UI automation).
* Python 3.12 or 3.13 (Python 3.13 is active in the current virtual environment).

### 1. Initialize Virtual Environment & Install Dependencies
Run the following in your command prompt:
```bash
# Install the locked production and test environments
uv sync --group dev
```

### 2. Offline Model Setup (Optional for Production Mode)
Create a `models/` directory in the root of the project to store neural network weights:
```bash
mkdir models
```
Ensure the following files/directories are downloaded and placed inside `./models/`:
1. **Silero VAD ONNX model**: `models/silero_vad.onnx`.
2. **CTranslate2 Whisper model**: `models/whisper-base/`. Production mode never downloads models at runtime.
3. **LLM GGUF model**: `models/qwen2.5-3b-instruct.Q4_K_M.gguf` (the default targeted LLM model).

Large Whisper and LLM weight files are intentionally excluded from GitHub to keep the repository cloneable. Download them separately into the paths above before running production mode.

*Note: If these weights are missing, the production adapters fall back gracefully to terminal-based inputs (STT) and rule-based parsing (LLM) so you can still run the production pipelines without issues.*

---

## Running the System

### A. Mock/Simulation Mode (No Model Downloads Needed)
Perfect for testing safety gates, confirmation states, and UI command logic without launching heavy ML models:
```bash
uv run python -m src.main
```
Type any command in the prompt (e.g., `open notepad`, `delete notes.txt`, `start dictating`) to trace how the orchestrator processes inputs.

### B. Production Mode (Real Windows APIs & Microphone)
To run the system with your real microphone, Windows UI window focuses, SAPI5 voice outputs, and offline ML models:
```bash
uv run python -m src.main --production
```

To diagnose or select a microphone explicitly:

```bash
uv run python -m src.main --list-audio-devices
uv run python -m src.main --production --input-device 12
```

Production mode requires all local models listed above. It will not download models or silently replace a failed production model with a network-backed service.

---

## Running Tests

We have written comprehensive tests validating the entire pipeline (state transitions, cancellations, emergency stops, UWP Notepad launches, COM saves, Word reader parsing).

Run the tests inside your virtualenv:
```bash
# Run all deterministic tests
uv run pytest

# Run machine-dependent hardware/GUI integration tests
uv run pytest -m integration
```

The normal suite does not open or close real applications. Hardware, TTS, and GUI checks are integration-only.
