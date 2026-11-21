# Project Blueprint
## AI Task Operator for Accessibility — [Project Name]

**Purpose of this file**: the stable anchor pasted into every AI coding session
(`@project_blueprint.md`). Mission, scope, and non-goals only — nothing that changes weekly.
Engineering detail (stack, schemas, interfaces, FR/NFR) lives in `technical_requirements.md`;
decision history lives in `records.md`. Don't duplicate those here.

---

## 1. Vision, Problem & Mission

**Vision**: to make computer interaction as natural as speaking, so visually impaired users can
operate a computer independently.

**Problem**: screen readers require memorizing hundreds of shortcuts; desktop AI agents assume the
user can see the screen; no offline conversational reasoning layer exists for non-technical
low-vision users today.

**Mission**: an offline, voice-operated accessibility layer for Windows that lets a low-vision or
blind user accomplish complete tasks through natural, conversational speech — not by memorizing
rigid command syntax. The system reasons about intent and orchestrates existing, mature OS
accessibility primitives (Windows UI Automation, Win32 COM) rather than reimplementing screen
reading or OS-level voice control from scratch. (See §7 Non-Goals for what this deliberately does
not replace.)

## 2. Target Persona

Primary: the user with acquired low vision (e.g. macular degeneration), limited prior
technical comfort, unable to self-configure developer-oriented tools like Talon or NVDA's advanced
settings. May have mild co-occurring hearing or motor changes typically — this
affects TTS pacing and STT tolerance expectations (see NFR-3 in `technical_requirements.md`).

Secondary persona is explicitly **not** designed for in MVP. If a working-age, higher-technical-comfort
user persona becomes a target later, that's a deliberate scope decision to make then, not one to
infer from this document.

## 3. Unique Value Proposition

Unlike Windows Voice Access or Talon Voice — which require exact command syntax — and unlike NVDA,
which reads the screen but has no reasoning layer, this system lets the user describe what they
want in plain, messy language and completes the task, while always confirming out loud before any
action that can't be trivially undone.

The core differentiator is the **reasoning and confirmation layer**, not any individual capability
(speech recognition, TTS, OS automation) — all of those are deliberately reused, not rebuilt. The
project's actual contribution is safely orchestrating mature, existing components into a
conversational accessibility layer for non-technical users — worth stating plainly for reports or
a viva, where "what did you actually build" is the first question.

## 4. Core Modes

Three-way state machine — see `technical_requirements.md` §6.3 (`StateMachine.route_transcript`)
for the routing logic:

- **Command Mode** — natural-language requests routed through the LLM intent parser (open/switch/
  close apps, start reading, start dictating)
- **Dictation Mode** — raw speech typed directly into the active field; bypasses the LLM entirely
  for latency and fidelity (never paraphrases the user's own words)
- **Reading Mode** — document playback with a fixed low-latency keyword set (pause/resume/next/
  repeat/stop) checked before falling through to Command Mode

## 5. MVP Scope

**In scope**: core voice loop, app open/switch/close (with tiered confirmation — see safety
principles below), PDF + DOCX reading with playback control, dictation with basic voice editing,
emergency stop, self-voicing zero-click installer.

**Explicitly out of scope for MVP**:
- UI element reading/clicking ("what are my options on screen")
- Multi-step task planning and cross-application workflows

- Context memory across sessions
- Wake-word activation (push-to-talk only for MVP)
- macOS / Linux support (Windows-only)

| Area | Status |
|---|---|
| Voice commands (open/switch/close) | MVP |
| Dictation + voice editing | MVP |
| PDF/DOCX reading + playback control | MVP |
| Emergency stop | MVP |
| UI element reading/clicking | Future |
| Wake word | Future |
| Multi-step planning | Future |
| Cross-app workflows | Future |
| Context memory | Future |

Full functional/non-functional requirement detail: `technical_requirements.md` §2–3.

## 6. Guiding Principles

- The human remains in control — the system proposes, never silently decides
- Safety before intelligence
- Accessibility over automation
- Offline before cloud
- Reuse before reinvent
- Explain before execute
- Simplicity before features

## 7. Non-Goals (Permanent, Not Just MVP-Deferred)

- Replacing NVDA, Windows Voice Access, or Talon Voice
- General-purpose desktop automation for sighted users
- Cloud-dependent operation — offline-first is a hard constraint, not a stretch goal
- Reading OS screen state via the NVDA Controller Client API (outbound-only; see
  `technical_requirements.md` §4 for the corrected integration path)

## 8. Safety Principles (Philosophy — implementation in `technical_requirements.md` §1)

- The LLM proposes structured intent; it never executes directly
- Actions are tiered by reversibility — irreversible actions require spoken confirmation and an
  explicit "Yes"; reversible actions proceed with post-action spoken feedback instead
- Emergency Stop runs on an isolated path, never queued behind the LLM
- No failure state is silent

## 9. Success Criteria (Qualitative — numeric targets live in `technical_requirements.md` NFRs)

- User opens/switches/closes applications using natural, non-scripted speech
- User dictates text successfully without paraphrasing/alteration
- User reads a PDF/DOCX naturally, with mid-read interruption working reliably
- No unsafe (unconfirmed, irreversible) action ever executes silently
- Entire system operates fully offline

## 10. System Overview (Plain-Language Flow)

```
Speech → Understand intent → Validate safety → Execute (or confirm first) → Speak result
```
Full interface-level diagram, class names, and stack: `technical_requirements.md` §6.3 and §9 —
deliberately not duplicated here.

## 11. User Journey (One Flow, No Implementation Detail)

```
Fresh Windows install → run installer → self-voicing setup (FR-10) → launch app →
push-to-talk → "Open Word" → dictate a paragraph → "read this PDF back to me" →
"close Word" → confirmed/auto-saved close → shutdown
```
This is the story every feature in §5 should serve — if a proposed feature doesn't fit somewhere
in this flow, question whether it belongs in MVP.

## 12. Assumptions

Product-level scoping assumptions (engineering constraints like CPU-only inference live in
`technical_requirements.md` NFR-1/NFR-4, not duplicated here):
- English and Hindi speech only for MVP
- A working microphone is present and accessible
- Single user per installation, not a multi-user/shared-machine scenario

## 13. Risks (Product-Level, Not Engineering Detail)

- Speech recognition accuracy on non-standard accents/pacing, background noise
- Office/third-party app UIA coverage gaps (some apps expose partial or no accessibility tree)
- PDF extraction quality on poorly-structured or scanned documents
- Local model latency on lower-spec target hardware

## 14. Future Roadmap (Phase-Ordered, Not MVP)

- **Phase 2**: wake word, UI element exploration, semantic document navigation
- **Phase 3**: cross-application workflows, context memory
- **Phase 4**: multi-step autonomous planning, browser support

Keeping this phase-ordered (not just a flat "deferred" list) helps prevent an AI session from
reaching for a Phase-4 idea while Phase-1 code is still being written.

## 15. Distribution Model

Not commercial until MVP is validated through design and testing. Dependency licensing is chosen
permissively regardless (MIT/BSD/Apache preferred, AGPL avoided) to avoid rework if commercialization
is pursued later — see `technical_requirements.md` §4 and §6.1.

## 16. Open Decisions Not Yet Locked

Stated explicitly so nothing gets silently assumed by an AI coding session. **Lifecycle note**:
these are pending items, not decisions — once resolved, an item moves OUT of this list and INTO
`records.md` as a proper ADR entry (decision + reasoning + rejected alternatives). **Hard cap: 3
items.** If resolving one pending item reveals two new ones, resolve something before adding —
this section growing is a signal to go make a decision now, not a place to accumulate them.

- [ ] **Whether the application will ever have any visual interface** (e.g. a future caregiver
  status panel or sighted-developer debug view). No decision has been made either way — do not
  instruct an AI assistant to hard-ban GUI code, and do not build one, until this is decided
  deliberately.
- [ ] Final LLM model selection (Phi-3-mini vs. Qwen2.5-3B — pending benchmark, see
  `technical_requirements.md` §6.1)
- [ ] Whether an NVDA add-on bridge integration is pursued post-MVP

## 17. Related Documents

- `technical_requirements.md` — engineering architecture, interfaces, stack, safety implementation
- `records.md` — architecture decision records (ADR), resolved from this file's §16 over time
- `README.md` — setup, installation, and repository overview

---

**When starting a new AI coding session**: provide this file plus `technical_requirements.md`.
This file tells the AI what and why; the other tells it how.
