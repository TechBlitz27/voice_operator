# Audio Fixture Dataset Specification - Voice Operator v1

This directory contains speech fixture recordings and replay definitions for validating Voice Operator v1's offline speech recognition, phonetic normalizer, and intent classification pipelines across linguistic and acoustic variations.

---

## 1. Specification & 20 Canonical Test Phrases

The dataset covers the 20 critical system commands, each specified in three speech styles:
1. **Plain English** (Standard/neutral pronunciation)
2. **Indian-accented English** (Phonetic shifts, e.g. aspirated consonants, rhotic retroflexes, vowels)
3. **Hinglish** (Code-switched colloquial command syntax)

| # | Canonical Command | Plain English Spoken | Indian-accented English Spoken | Hinglish Spoken | Expected Intent | Target Entity / Action |
|---|-------------------|----------------------|--------------------------------|-----------------|-----------------|------------------------|
| 1 | Open Chrome | "Open Chrome" | "Open Chrome" | "Chrome kholo" | `open_app` | `chrome` |
| 2 | Close Chrome | "Close Chrome" | "Close Chrome" | "Chrome band karo" | `close_app` | `chrome` |
| 3 | Switch to Chrome | "Switch to Chrome" | "Switch to Chrome" / "Which to Chrome" | "Chrome switch karo" | `switch_app` | `chrome` |
| 4 | Open Word | "Open Word" | "Open Word" | "Word kholo" | `open_app` | `word` |
| 5 | Close Word | "Close Word" | "Close Word" | "Word band karo" | `close_app` | `word` |
| 6 | Switch to Word | "Switch to Word" | "Switch to Word" | "Word switch karo" | `switch_app` | `word` |
| 7 | Open Excel | "Open Excel" | "Open Excel" | "Excel kholo" | `open_app` | `excel` |
| 8 | Close Excel | "Close Excel" | "Close Excel" | "Excel band karo" | `close_app` | `excel` |
| 9 | Switch to Excel | "Switch to Excel" | "Switch to Excel" / "Which 2 Excel" | "Excel switch karo" | `switch_app` | `excel` |
| 10 | Open Notepad | "Open Notepad" | "Open Notepad" / "Open note pad" | "Notepad kholo" | `open_app` | `notepad` |
| 11 | Close Notepad | "Close Notepad" | "Close Notepad" | "Notepad band karo" | `close_app` | `notepad` |
| 12 | Switch to Notepad | "Switch to Notepad" | "Switch to Notepad" | "Notepad switch karo" | `switch_app` | `notepad` |
| 13 | Start Dictation | "Start dictation" | "Start dictation" / "Start dictating" | "Dictation shuru karo" | `type_text` | Dictation Mode Entry |
| 14 | Stop Dictation | "Stop dictation" | "Stop dictation" / "Stop dictating" | "Dictation band karo" | `mode_switch` | Command Mode Return |
| 15 | Read this document | "Read this document" | "Read this document" | "Ye document padho" | `read_document` | Reading Mode Entry |
| 16 | Stop | "Stop" | "Stop" | "Ruk jao" / "Stop" | `emergency_stop` | System-wide Halt |
| 17 | Pause | "Pause" | "Pause" | "Pause karo" / "Ruko" | `reading_control` | Pause Document Playback |
| 18 | Resume | "Resume" | "Resume" | "Resume karo" / "Dobara shuru karo" | `reading_control` | Resume Document Playback |
| 19 | Yes | "Yes" | "Yes please" | "Haan" / "Sahi hai" | `confirmation` | Authorize Pending Action |
| 20 | No | "No" | "No thanks" | "Nahi" / "Mat karo" | `cancellation` | Reject Pending Action |

---

## 2. Recording & Audio Encoding Standards

All recorded fixture WAV files must adhere to the following hardware capture constraints:

1. **Sampling Rate**: `16,000 Hz` (16 kHz). Matches faster-whisper and Silero VAD native model input.
2. **Channel Format**: `1 Channel` (Mono). Downmixed without stereo phasing.
3. **Encoding & Bit Depth**: `16-bit Signed Linear PCM` (WAV format, `audio/wav`).
4. **Noise Floor & SNR**: Measured ambient SNR >= `20 dB`. Baseline RMS < `100.0` during leading/trailing silence.
5. **Headroom & Normalization**: Peak amplitude between `-3.0 dBFS` and `-6.0 dBFS`. No digital clipping or saturation.
6. **Padding**: 150ms to 250ms leading and trailing acoustic silence margin to verify VAD edge triggering.

---

## 3. Fixture File Naming Convention

Fixtures in this directory follow the standardized naming schema:
```
p<index>_<command_slug>_<accent>.<ext>
```
Examples:
- `p01_open_chrome_en.wav` (Phrase 1, Plain English)
- `p01_open_chrome_in.wav` (Phrase 1, Indian-accented English)
- `p01_open_chrome_hi.wav` (Phrase 1, Hinglish)
- `p13_start_dictation_en.wav`
- `p16_stop_en.wav`

---

## 4. Replay Testing Harness

A dedicated regression harness runs every fixture file through the local faster-whisper speech recognizer and intent parser:
```bash
# Run the real STT replay test suite:
uv run pytest tests/audio/test_replay.py -s
```

The replay suite outputs a structured pass/fail table evaluating:
- **Word Error Rate (WER)**: Levenshtein distance on tokenized word sequences.
- **Intent Match**: Semantic alignment between the recognized command and expected executor action.
