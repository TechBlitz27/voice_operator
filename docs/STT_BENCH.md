# Whisper STT Benchmark on Indian-Accented English Audio Fixtures

Date: 2026-10-17
Hardware: Windows CPU (Intel Core)
Compute Type: int8
Task: transcribe (no translation)

| Model | Intent Accuracy | Pass Rate | Average WER | Avg Latency (s) | Meets Goal (<2s & >=90%) |
|---|---|---|---|---|---|
| **whisper-base** | **90.0%** | 18/20 | 0.17 | 0.96s | **YES (Recommended)** |
| **whisper-small.en** | **85.0%** | 17/20 | 0.20 | 1.45s | **NO** |
| **whisper-small** | **85.0%** | 17/20 | 0.20 | 2.91s | **NO** |

## Detailed Breakdown Per Model

### Model: whisper-base

| Fixture | Reference | Transcribed | WER | Expected Intent | Matched Intent | Status | Latency |
|---|---|---|---|---|---|---|---|
| p01_open_chrome_en.wav | open chrome | Open Chrome. | 0.00 | open_app(chrome) | open_app(chrome) | PASS | 1.09s |
| p02_close_chrome_en.wav | close chrome | Close Crow. | 0.50 | close_app(chrome) | close_app(crow) | FAIL | 0.98s |
| p03_switch_chrome_en.wav | switch chrome | switch to crow | 1.00 | switch_app(chrome) | switch_app(crow) | FAIL | 0.99s |
| p04_open_word_en.wav | open word | Open word. | 0.00 | open_app(word) | open_app(word) | PASS | 0.94s |
| p05_close_word_en.wav | close word | Close word. | 0.00 | close_app(word) | close_app(word) | PASS | 0.95s |
| p06_switch_word_en.wav | switch word | Switch to Word. | 0.50 | switch_app(word) | switch_app(word) | PASS | 0.98s |
| p07_open_excel_en.wav | open excel | Open Excel | 0.00 | open_app(excel) | open_app(excel) | PASS | 0.95s |
| p08_close_excel_en.wav | close excel | Close Excel | 0.00 | close_app(excel) | close_app(excel) | PASS | 0.95s |
| p09_switch_excel_en.wav | switch excel | Switch to Excel. | 0.50 | switch_app(excel) | switch_app(excel) | PASS | 1.00s |
| p10_open_notepad_en.wav | open notepad | Open notepad | 0.00 | open_app(notepad) | open_app(notepad) | PASS | 0.94s |
| p11_close_notepad_en.wav | close notepad | Close notepad | 0.00 | close_app(notepad) | close_app(notepad) | PASS | 0.94s |
| p12_switch_notepad_en.wav | switch notepad | switch to notepad | 0.50 | switch_app(notepad) | switch_app(notepad) | PASS | 0.95s |
| p13_start_dictation_en.wav | start dictation | Start dictation | 0.00 | type_text(dictation) | type_text(dictation) | PASS | 0.94s |
| p14_stop_dictation_en.wav | stop dictation | Stop dictation. | 0.00 | mode_switch(command) | mode_switch(command) | PASS | 1.00s |
| p15_read_document_en.wav | read document | Read this document. | 0.50 | read_document(document) | read_document(document) | PASS | 0.93s |
| p16_stop_en.wav | stop | stop | 0.00 | emergency_stop(global) | emergency_stop(global) | PASS | 0.91s |
| p17_pause_en.wav | pause | Pause | 0.00 | reading_control(pause) | reading_control(pause) | PASS | 0.92s |
| p18_resume_en.wav | resume | resume | 0.00 | reading_control(resume) | reading_control(resume) | PASS | 0.91s |
| p19_yes_en.wav | yes | Yes. | 0.00 | confirmation(yes) | confirmation(yes) | PASS | 0.93s |
| p20_no_en.wav | no | No. | 0.00 | cancellation(no) | cancellation(no) | PASS | 0.93s |

### Model: whisper-small.en

| Fixture | Reference | Transcribed | WER | Expected Intent | Matched Intent | Status | Latency |
|---|---|---|---|---|---|---|---|
| p01_open_chrome_en.wav | open chrome | Open CRO. | 0.50 | open_app(chrome) | open_app(cro) | FAIL | 1.46s |
| p02_close_chrome_en.wav | close chrome | close crow | 0.50 | close_app(chrome) | close_app(crow) | FAIL | 1.40s |
| p03_switch_chrome_en.wav | switch chrome | Switch to crow | 1.00 | switch_app(chrome) | switch_app(crow) | FAIL | 1.40s |
| p04_open_word_en.wav | open word | Open Word | 0.00 | open_app(word) | open_app(word) | PASS | 1.57s |
| p05_close_word_en.wav | close word | close word | 0.00 | close_app(word) | close_app(word) | PASS | 1.43s |
| p06_switch_word_en.wav | switch word | Switch to Word | 0.50 | switch_app(word) | switch_app(word) | PASS | 1.47s |
| p07_open_excel_en.wav | open excel | Open Excel | 0.00 | open_app(excel) | open_app(excel) | PASS | 1.42s |
| p08_close_excel_en.wav | close excel | Close excel | 0.00 | close_app(excel) | close_app(excel) | PASS | 1.40s |
| p09_switch_excel_en.wav | switch excel | Switch to excel | 0.50 | switch_app(excel) | switch_app(excel) | PASS | 1.41s |
| p10_open_notepad_en.wav | open notepad | Open Notepad | 0.00 | open_app(notepad) | open_app(notepad) | PASS | 1.51s |
| p11_close_notepad_en.wav | close notepad | Close notepad | 0.00 | close_app(notepad) | close_app(notepad) | PASS | 1.42s |
| p12_switch_notepad_en.wav | switch notepad | Switch to notepad | 0.50 | switch_app(notepad) | switch_app(notepad) | PASS | 1.43s |
| p13_start_dictation_en.wav | start dictation | Start dictation. | 0.00 | type_text(dictation) | type_text(dictation) | PASS | 1.53s |
| p14_stop_dictation_en.wav | stop dictation | Stop dictation | 0.00 | mode_switch(command) | mode_switch(command) | PASS | 1.47s |
| p15_read_document_en.wav | read document | Read this document. | 0.50 | read_document(document) | read_document(document) | PASS | 1.50s |
| p16_stop_en.wav | stop | Stop | 0.00 | emergency_stop(global) | emergency_stop(global) | PASS | 1.52s |
| p17_pause_en.wav | pause | Pause | 0.00 | reading_control(pause) | reading_control(pause) | PASS | 1.42s |
| p18_resume_en.wav | resume | Resume | 0.00 | reading_control(resume) | reading_control(resume) | PASS | 1.42s |
| p19_yes_en.wav | yes | Yes. | 0.00 | confirmation(yes) | confirmation(yes) | PASS | 1.43s |
| p20_no_en.wav | no | No. | 0.00 | cancellation(no) | cancellation(no) | PASS | 1.41s |

### Model: whisper-small

| Fixture | Reference | Transcribed | WER | Expected Intent | Matched Intent | Status | Latency |
|---|---|---|---|---|---|---|---|
| p01_open_chrome_en.wav | open chrome | Open crow | 0.50 | open_app(chrome) | open_app(crow) | FAIL | 2.90s |
| p02_close_chrome_en.wav | close chrome | Close crow | 0.50 | close_app(chrome) | close_app(crow) | FAIL | 3.17s |
| p03_switch_chrome_en.wav | switch chrome | switch to crow | 1.00 | switch_app(chrome) | switch_app(crow) | FAIL | 3.09s |
| p04_open_word_en.wav | open word | Open Word | 0.00 | open_app(word) | open_app(word) | PASS | 2.82s |
| p05_close_word_en.wav | close word | Close Word | 0.00 | close_app(word) | close_app(word) | PASS | 2.77s |
| p06_switch_word_en.wav | switch word | Switch to Word. | 0.50 | switch_app(word) | switch_app(word) | PASS | 2.83s |
| p07_open_excel_en.wav | open excel | Open Excel. | 0.00 | open_app(excel) | open_app(excel) | PASS | 3.03s |
| p08_close_excel_en.wav | close excel | Close Excel. | 0.00 | close_app(excel) | close_app(excel) | PASS | 2.83s |
| p09_switch_excel_en.wav | switch excel | Switch to Excel | 0.50 | switch_app(excel) | switch_app(excel) | PASS | 2.94s |
| p10_open_notepad_en.wav | open notepad | Open Notepad | 0.00 | open_app(notepad) | open_app(notepad) | PASS | 2.91s |
| p11_close_notepad_en.wav | close notepad | Close notepad. | 0.00 | close_app(notepad) | close_app(notepad) | PASS | 2.97s |
| p12_switch_notepad_en.wav | switch notepad | Switch to Notepad. | 0.50 | switch_app(notepad) | switch_app(notepad) | PASS | 2.97s |
| p13_start_dictation_en.wav | start dictation | Start dictation. | 0.00 | type_text(dictation) | type_text(dictation) | PASS | 2.89s |
| p14_stop_dictation_en.wav | stop dictation | Stop Dictation | 0.00 | mode_switch(command) | mode_switch(command) | PASS | 2.87s |
| p15_read_document_en.wav | read document | Read this document. | 0.50 | read_document(document) | read_document(document) | PASS | 2.82s |
| p16_stop_en.wav | stop | Stop | 0.00 | emergency_stop(global) | emergency_stop(global) | PASS | 2.81s |
| p17_pause_en.wav | pause | Pause. | 0.00 | reading_control(pause) | reading_control(pause) | PASS | 2.82s |
| p18_resume_en.wav | resume | resume | 0.00 | reading_control(resume) | reading_control(resume) | PASS | 2.87s |
| p19_yes_en.wav | yes | Yes. | 0.00 | confirmation(yes) | confirmation(yes) | PASS | 2.84s |
| p20_no_en.wav | no | No. | 0.00 | cancellation(no) | cancellation(no) | PASS | 2.97s |

