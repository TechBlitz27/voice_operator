# Technical Requirements
## AI Task Operator for Accessibility — [Project Name]

**Status:** MVP stack locked. Two items intentionally left flexible (LLM model, concurrency
implementation detail) — see §6 and §3 respectively.

---

## 1. Safety-Critical Requirements

These are non-negotiable — the reason this document exists ahead of a generic technical spec.
A blind/low-vision user cannot visually catch a misfired action, so every design decision below
answers to this section first.

| ID | Requirement |
| --- | --- |
| SAFE-1 | The LLM never executes an action directly. It only proposes a structured intent object. |
| SAFE-2 | Every LLM output passes a two-stage validation gate before reaching the executor: **(a)** the selected LLM runtime must support grammar-constrained (or equivalent schema-constrained) structured output — currently satisfied by `llama.cpp`'s GBNF grammars — guaranteeing syntactic JSON validity; **(b)** `pydantic` schema validation checks the parsed object against the action whitelist and parameter sanity. This is stated as a runtime *requirement*, not tied to `llama.cpp` specifically, since the requirement should outlive any one runtime choice — grammar constraints guarantee valid JSON shape, not semantic correctness, so both gates are mandatory regardless of backend. |
| SAFE-3 | Actions are tiered by reversibility, not treated uniformly (see §2, action tier table). Irreversible actions (delete, send) require spoken confirmation and an explicit "Yes" before execution. Reversible actions (open, switch, close-with-autosave) proceed without pre-confirmation but always produce spoken post-action feedback. |
| SAFE-4 | `close_app` requires successful auto-save (or confirmed no-unsaved-content) before proceeding. If auto-save cannot be verified (e.g., an unsaved-changes dialog appears), the action escalates to the confirmation-required path — it does not silently proceed. |
| SAFE-5 | An "undo last action" command is a first-class whitelisted action — reopens the last-closed app and, where the file path is known, reopens the document. This is the practical safety net behind SAFE-3's no-pre-confirmation tier. |
| SAFE-6 | The Emergency Stop mechanism runs on a dedicated, isolated OS thread with direct access to halt audio playback and cancel pending execution. It is never queued behind the LLM pipeline — a slow or blocked pipeline must not delay a stop request. |
| SAFE-7 | No failure state is silent. Every failure mode (STT low confidence, UIA element not found, ambiguous/schema-rejected intent, OCR/extraction failure) produces an audible message before the system returns to idle. |

---

## 2. MVP Functional Requirements

Locked scope: core voice loop, app lifecycle (open/switch/close), document reading (PDF + DOCX)
with playback control, dictation with basic voice editing. **Explicitly excluded from MVP**: UI
element reading/clicking, multi-step task planning, cross-app workflows, file search/management,
context memory across sessions, wake-word activation (push-to-talk only).

| ID | Requirement |
| --- | --- |
| FR-1 | System converts push-to-talk-captured speech into a structured intent object via local STT + LLM parsing. |
| FR-2 | System constrains LLM output to a bounded action schema (§6.2); any output failing validation triggers a spoken clarification request, not a best-effort execution attempt. |
| FR-3 | System opens, switches to, and closes applications on request. |
| FR-4 | System reads PDF and DOCX documents aloud via TTS. |
| FR-5 | System supports playback control while reading: pause, resume, repeat last sentence, skip to next paragraph. |
| FR-6 | System supports voice dictation of new text into the active application's text field. |
| FR-7 | System supports basic voice-editing commands during dictation: delete last word, new paragraph, capitalize. |
| FR-8 | **The main STT pipeline** drops/ignores audio frames during TTS playback (queried via `SpeechSynthesizer.is_speaking()`) to prevent feedback-loop self-triggering. **The raw microphone stream is never hardware-muted** — it remains continuously open for the dedicated low-latency listener (§1 SAFE-6), which stays active throughout TTS playback specifically so the user can interrupt. *(Corrected — original wording implied full mic gating, which would have made the Emergency Stop thread deaf exactly when a long document readout makes it most needed.)* |
| FR-8a | The dedicated low-latency listener (SAFE-6) recognizes a small fixed keyword set at all times, independent of TTS state: **stop**, **pause**, **resume**, **next** (paragraph), **repeat** (last sentence) — not just the emergency "stop" word. FR-5's playback controls only work mid-reading if they're on this always-on path, not the gated main pipeline. |
| FR-9 | System provides an audible error state for every defined failure mode — no silent failures (maps to SAFE-7). |
| FR-10 | System completes first-run setup via a self-voicing installer requiring zero sighted assistance and zero mouse clicks. |
| FR-11 | System supports a global "Stop" / emergency halt command at all times (maps to SAFE-6). |
| FR-12 | System supports "undo last action" to reverse the most recent close/open action (maps to SAFE-5). |

### Action Tier Table (implements SAFE-3, SAFE-4)

| Action | Pre-confirmation | Auto-save required | Post-action spoken feedback |
| --- | --- | --- | --- |
| `open_app` | No | N/A | Optional |
| `switch_app` | No | N/A | Optional |
| `close_app` | No (unless auto-save fails/dialog appears) | Yes | Yes — "Closed [app]" |
| `delete_file` | **Yes — wait for "Yes"** | N/A | Yes |
| `send_email` | **Yes — wait for "Yes"** | N/A | Yes |
| `read_document` | No | N/A | N/A |
| `navigate_document` | No | N/A | N/A |
| `type_text` (dictation) | No | N/A | N/A |
| `undo_last_action` | No | N/A | Yes |
| `ambiguous` | N/A — triggers clarification request, not execution | N/A | N/A |

---

## 3. Non-Functional Requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | Local LLM intent-parsing latency < 800ms on reference hardware [specify: Intel i5-equivalent, no GPU]. |
| NFR-2 | **End-to-end** latency (end of user speech → start of spoken confirmation/response) < 2000ms. This is the user-perceived metric — NFR-1 alone does not demonstrate usability. *(Note: earlier drafts inconsistently cited 1500ms; 2000ms is the locked value — confirm final if hardware benchmarking suggests otherwise.)* |
| NFR-3 | STT word error rate on target-persona voice samples (age 60+, [specify any relevant speech characteristics]) ≤ [X]% — benchmark against real target-demographic recordings, not general benchmark corpora. |
| NFR-4 | System operates with zero network connectivity for all core functions (offline-first). |
| NFR-5 | False-action rate (state-changing action executed without the required confirmation per §2's tier table) = 0 in test suite — non-negotiable safety threshold, not a target to approach. |
| NFR-6 | Extraction-confidence flags are spoken audibly when document text extraction quality is degraded (e.g., malformed PDF structure) below [X]% confidence. |
| NFR-7 | Setup-to-first-successful-command time < [X] minutes, zero sighted assistance. |
| NFR-8 | The system shall support concurrent processing of audio capture, speech synthesis, and command execution such that an in-progress operation on one channel does not block responsiveness on another — in particular, the Emergency Stop path (SAFE-6) must remain responsive regardless of main-pipeline state. *Implementation intent: `asyncio` for the main sequential pipeline (VAD→STT→LLM→TTS), with the Emergency Stop kept as a genuine OS thread outside the event loop specifically because cooperative scheduling could otherwise delay a stop request. This is the current design intent, to be validated against SAFE-6 during prototyping rather than treated as a fixed implementation constraint.* |

---

## 4. Technical Constraints

- Windows-only for MVP (UIA/COM dependency)
- The NVDA Controller Client API will not be used for screen-state input — it is outbound-only
  (speech/braille output). UIA is the sanctioned read path for MVP; a custom NVDA add-on bridge
  is an optional, deferred integration.
- **No application code calls a third-party library directly.** All external dependencies are
  accessed through an internal interface (§6.3) — this is a standing architectural rule, not a
  per-component decision.
- Distribution model is undecided pending MVP success (not commercial until MVP is validated) —
  dependency licensing choices (§6.1) are made permissively regardless, to avoid rework if/when
  commercialization is pursued.

---

## 5. Dependency Selection Principles

Every third-party dependency is evaluated against this checklist before adoption:

- ✓ Open source (strong preference)
- ✓ Offline-capable
- ✓ Windows-supported
- ✓ Actively maintained
- ✓ Python API available
- ✓ Well documented
- ✓ Wrapped behind an internal interface (§4) — never called directly from application logic
- ✓ Permissive license preferred; copyleft (AGPL/GPL) dependencies require an explicit, documented
  reason and distribution-model check (see §6.1 PDF note)

---

## 6. Final Technology Stack

### 6.1 Locked Components

| Interface | Concrete Implementation | License | Notes |
| --- | --- | --- | --- |
| `AudioSource` | `sounddevice` | MIT | Preferred over `PyAudio` — cleaner Windows install, no missing-wheel issues |
| `VoiceActivityDetector` | `silero-vad` | MIT | Neural VAD — handles slower/elderly speech pacing better than energy-threshold VAD (NFR-3) |
| `SpeechRecognizer` | `faster-whisper` | MIT | CTranslate2-optimized local Whisper |
| — Trigger | Push-to-talk via `keyboard` (global hotkey) | MIT | Wake-word (`openWakeWord`/Porcupine) explicitly deferred to v2 |
| `LLMProvider` | `llama-cpp-python` (in-process GGUF inference) | MIT | Chosen over `Ollama` specifically to satisfy FR-10 (zero-daemon, zero-click installer) — no external service process required. `OllamaProvider` may exist as a secondary implementation for dev-time benchmarking convenience. |
| — Schema enforcement | GBNF grammar (via `llama.cpp`) + `pydantic` | MIT | Two-stage gate per SAFE-2 |
| `DocumentReader` (PDF) | `pdfplumber` | MIT | **Not** PyMuPDF — PyMuPDF is dual-licensed AGPL-3.0/commercial; distributing a closed-source build would require a paid Artifex license or open-sourcing the app. Locked to avoid rework if commercialization proceeds post-MVP. |
| `DocumentReader` (DOCX) | `python-docx` | MIT | |
| `OSController` — window/app lifecycle | `pywinauto` + `uiautomation` | BSD / Apache-2.0 | Primary automation layer — semantic UIA, not screenshot/coordinate-based |
| `OSController` — Office deep control | `pywin32` (Win32 COM) | PSF | Used specifically for `Document.Save()` on Office apps — real auto-save, not a simulated Ctrl+S that can miss a Save-As dialog |
| `OSController` — process inspection | `psutil` + `subprocess` | BSD | Check running state before open/switch decisions |
| — Dictation/keystroke fallback | `keyboard` | MIT | Last-resort fallback only, not primary automation |
| `SpeechSynthesizer` | `pyttsx3` (Windows SAPI5) | MIT wrapper | Zero-latency, zero-download; Piper deferred to v2 for higher-quality voice |
| — Emergency stop | Dedicated OS thread, keyword-spotted, direct `sounddevice.stop()` | — | See NFR-8 and SAFE-6 |
| — Config | TOML + `pydantic-settings`, split into `config.toml` / `voices.toml` / `models.toml` rather than one monolithic file | MIT | |
| — Logging | stdlib `logging`, structured fields (timestamp, module, action, latency, status) rather than plain message strings | PSF | Loguru explicitly deferred — no need for it yet; structured fields matter more than the library for later debugging |
| — Testing | `pytest` | MIT | |
| — Packaging | `PyInstaller` | GPL (tool only, not your distributed output) | |
| — Env/dependency management | Python 3.12 + `uv` (commit `uv.lock` for reproducibility) + `Ruff` | PSF / MIT | 3.12 pinned for prebuilt-wheel compatibility (`llama-cpp-python`, `pywin32`); reassess 3.13 once wheel coverage is verified. `Ruff` for linting/formatting from day one. |

### 6.2 LLM Action Schema

**This is what the LLM is constrained to output** (via GBNF grammar, SAFE-2a). It does not
include `requires_confirmation` — asking the model to produce a field you then override wastes
tokens/latency and creates a real risk of a developer reading the LLM's guess instead of doing
the table lookup. Caught late; fixed here.

```json
{
  "intent_confidence": 0.0,
  "action": "open_app | close_app | switch_app | delete_file | send_email | read_document | navigate_document | type_text | undo_last_action | ambiguous",
  "target": "",
  "parameters": {}
}
```

**This is the internal executor-facing schema**, produced by `StateMachine` after the LLM output
passes `pydantic` validation (SAFE-2b) — `requires_confirmation` is appended here, looked up from
the action tier table (§2), never read from the LLM's output:

```json
{
  "intent_confidence": 0.0,
  "action": "...",
  "target": "",
  "parameters": {},
  "requires_confirmation": true
}
```

### 6.3 Interface Contracts (draft first, before any concrete implementation)

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List

class AudioSource(ABC):
    @abstractmethod
    def start_stream(self) -> None: ...
    @abstractmethod
    def read_chunk(self) -> bytes: ...
    @abstractmethod
    def stop_stream(self) -> None: ...
    # Refined from a single vague stream() — audio capture is a lifecycle
    # (start/read/stop), not a one-shot call; avoids a near-certain later redesign.

class VoiceActivityDetector(ABC):
    @abstractmethod
    def is_speech(self, audio_chunk: bytes) -> bool: ...

class SpeechRecognizer(ABC):
    @abstractmethod
    def transcribe(self, audio_data: bytes) -> str: ...

class LLMProvider(ABC):
    @abstractmethod
    def generate_action(self, prompt: str, schema: Dict[str, Any]) -> Dict[str, Any]: ...

class DocumentReader(ABC):
    @abstractmethod
    def extract_text_chunks(self, file_path: str) -> List[str]: ...

class StateMachine(ABC):
    @abstractmethod
    def route(self, validated_intent: Dict[str, Any]) -> Dict[str, Any]:
        """Owns mode transitions (Command/Dictation/Reading) and the action-tier
        confirmation logic (§2). Decides whether to invoke SpeechSynthesizer for a
        confirmation prompt and await 'Yes' before calling OSController, based on
        the action tier table — this logic does not live in the validator or executor."""
        ...

    @abstractmethod
    def route_transcript(self, raw_text: str) -> Dict[str, Any]:
        """Entry point BEFORE the LLM. Three-way branch on current mode — made
        explicit here because an unstated third mode is exactly the kind of gap
        that caused the original dictation-bypass bug:

        - Dictation Mode → raw_text goes directly to OSController.type_text (after
          a lightweight local keyword check for edit commands like 'delete last
          word' / 'new paragraph' / 'stop dictating'). Never touches LLMProvider —
          sending dictated paragraphs through the intent LLM risks it summarizing
          or altering the user's exact words, and adds needless latency to a mode
          that requires no reasoning.
        - Reading Mode → raw_text is checked against the fixed low-latency keyword
          set (FR-8a: pause/resume/next/repeat/stop) first; anything else falls
          through to Command Mode handling below (e.g. "read a different file").
        - Command Mode → forwarded to LLMProvider as normal (main pipeline, §9).

        Entering/exiting Dictation or Reading Mode ('start dictating', 'read this
        PDF', 'stop dictating') IS parsed by the LLM as a mode-switch intent —
        only in-mode content/keywords bypass it."""
        ...

class OSController(ABC):
    @abstractmethod
    def execute_action(self, action_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Single entry point called by StateMachine — takes the generic validated
        action schema, returns a status dict (not a bare bool) per SAFE-4, e.g.
        {'success': True, 'autosave_ok': True} or
        {'success': False, 'dialog_detected': 'unsaved_changes'}.

        NOTE on implementation (reconciles a naming disagreement across reviews):
        keep this as the ONE interface method StateMachine calls — it shouldn't need
        to know per-action method names. Internally, a concrete implementation should
        dispatch to its own semantic private methods (_open_application,
        _close_application, _switch_application, _save_document, _focus_window) for
        readability and unit-testability, then have execute_action() be a thin
        dispatcher over them. Both the "single entry point" and "clear semantic
        methods" goals are satisfied this way — they aren't actually in tension."""
        ...
    @abstractmethod
    def type_text(self, text: str) -> bool:
        """Direct dictation-content injection, called by StateMachine.route_transcript
        when in Dictation Mode — bypasses execute_action/LLM entirely (see
        StateMachine.route_transcript above)."""
        ...

class SpeechSynthesizer(ABC):
    @abstractmethod
    def speak(self, text: str, interruptible: bool = True) -> None: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def is_speaking(self) -> bool:
        """Required by FR-8's corrected gating logic — the main STT pipeline checks
        this to decide whether to drop incoming audio frames. Without it, pause/
        resume/emergency-stop/mic-gating interactions become unmanageable, as flagged
        in review."""
        ...
```

### 6.4 Deferred / Not Chosen for MVP

Explicitly out of scope for now — do not evaluate libraries for these until the corresponding
feature is pulled into scope:

- OCR (Tesseract / PaddleOCR / EasyOCR) — no scanned-document support in MVP
- Vector DB / embeddings (ChromaDB / FAISS / Qdrant) — no long-term memory/semantic retrieval in MVP
- Browser automation — not in scope, matches PRD non-goals
- Wake-word engine — push-to-talk only for MVP

---

## 7. Project Structure

Defined before implementation begins — cheap now, expensive to retrofit after code exists.

```
src/
    core/
        interfaces/         # ABCs from §6.3 — the only thing app logic imports directly
        models/              # pydantic schema definitions (§6.2)
        state_machine/       # StateMachine implementation — mode + confirmation logic
    adapters/                # one folder per concrete implementation of a §6.3 interface
        whisper/              # SpeechRecognizer impl
        llama_cpp/            # LLMProvider impl
        pyttsx3/               # SpeechSynthesizer impl
        pdf/                    # DocumentReader impl (pdfplumber)
        word/                   # DocumentReader impl (python-docx)
        windows/               # OSController impl (pywinauto/uiautomation/pywin32)
    services/                # orchestration that composes adapters via interfaces
        speech/
        intent/
        document/
        dictation/
    config/
    tests/
    main.py                  # Entry point — config loading, thread init (Emergency Listener spun up here)
    orchestrator.py           # Composition root — wires adapters to interfaces, owns the main pipeline loop
```

No file under `adapters/` is imported anywhere outside `services/` — enforces the Technical
Constraints §4 rule ("no application code calls a third-party library directly") structurally,
not just by convention.

---

## 8. Error Handling Strategy

Every failure mode maps to a defined response, not ad-hoc handling per callsite:

| Concern | Policy |
|---|---|
| Retry policy | STT/LLM calls: 1 silent retry on timeout before surfacing a spoken error (SAFE-7) — do not retry silently more than once, a hung retry loop is itself a silent failure from the user's perspective |
| Timeouts | Every external call (STT, LLM inference, UIA action) has an explicit timeout tied to NFR-1/NFR-2's latency budget — a hang must become a spoken error, not an indefinite wait |
| Fallback strategy | UIA element not found → spoken error + no action taken (never guess); OCR/extraction low-confidence → spoken confidence flag (NFR-6), not a silent best-effort read |
| User feedback | Every failure branch has a defined spoken message (see §2 error-state table, to be filled in during implementation — one row per failure mode identified here) |
| Logging | Structured fields per §6.1 — every failure logs timestamp/module/action/latency/status for post-hoc debugging without needing to reproduce the failure live |
| Recovery | `undo_last_action` (SAFE-5) is the general recovery mechanism for action-level mistakes; failures within a single action (e.g., STT mis-transcription) recover via re-prompt, not partial execution |

---

## 9. Architecture Diagram (Interface-Level)

```
AudioSource
     │
     ▼
VoiceActivityDetector
     │
     ▼
SpeechRecognizer
     │
     ▼
StateMachine.route_transcript(raw_text) ──┬── Dictation Mode? ──► OSController.type_text()
                                           │                       (bypasses LLM entirely — FR-6/7)
                                           │
                                           └── Command Mode ──► LLMProvider
                                                                     │
                                                                     ▼
                                                    (GBNF grammar-constrained JSON)
                                                                     │
                                                                     ▼
                                                    Pydantic Safety Validator
                                                                     │
                                                                     ▼
                                    StateMachine.route() ──► action tier lookup (§2),
                                                              mode transitions
                                                                     │
                              ├─── requires_confirmation? ──► SpeechSynthesizer (confirm) ──► wait for "Yes"
                                                                     │
                                                                     ▼
                              OSController.execute_action() / DocumentReader
                                    (execution — returns status dict, not bare bool, per SAFE-4)
                                                                     │
                                                                     ▼
                                                    SpeechSynthesizer (post-action feedback)

  [Parallel, always-on, outside this pipeline, mic never hardware-muted — FR-8/FR-8a:]
  Low-Latency Listener (dedicated thread) ──► keyword set: stop / pause / resume / next / repeat
                                          ──► direct interrupt ──► AudioSource.stop_stream(),
                                                                    SpeechSynthesizer.stop(),
                                                                    cancel pending execution
```