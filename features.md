## 1. The Core Philosophy
The rule for how this app behaves: **The user cannot see the screen.**
Therefore, every action must have an auditory confirmation, and the user must be able to ask *"Where am I?"* or *"What can I do here?"* at any time.


## 2. Feature Master List (The Vision)

Here is everything the software needs to do to fulfill our goal of replacing a mouse and keyboard with pure voice control.

### Category A: System & State Management

* **Wake / Sleep:** Always listening for a trigger (e.g., *"Operator, wake up"* / *"Operator, go to sleep"*).
* **Emergency Stop:** A global override command (e.g., *"Stop listening"*) that immediately halts any reading or action.
* **Context Awareness:** The user can ask, *"What app is currently open?"* and the system will reply (e.g., *"You are in Microsoft Word"*).

### Category B: OS & Window Navigation

* **App Launching:** *"Open Google Chrome,"* *"Launch Notepad."*
* **Window Management:** *"Switch to my PDF,"* *"Minimize this window,"* *"Close this app."*
* **UI Interaction:** The system can read the Windows Accessibility Tree. User asks: *"What are my options?"* System reads buttons: *"Submit, Cancel, Help."* User says: *"Click Submit."*

### Category C: Document Reading (PDF, Word, Text)

* **Continuous Reading:** The system extracts text from a file and reads it aloud.
* **Granular Playback Control:** The user can interrupt and say, *"Pause,"* *"Resume,"* *"Repeat the last sentence,"* or *"Skip to the next paragraph."*
* **Summarization (AI):** *"Give me a summary of this document before you read the whole thing."*

### Category D: Writing & Dictation

* **Mode Switching:** Explicit command to enter typing mode (e.g., *"Start dictating"*).
* **Text Injection:** Converts speech to text and types it directly into the active window.
* **Voice Editing:** Commands like *"Delete the last word,"* *"New paragraph,"* or *"Capitalize that."*



## 3. The MVP Scope (What we build first)

If we try to build everything above for version 1.0, the AI context will get too complicated and the code will break. The MVP must prove the core loop works.

Here is the strict cutoff for the **Minimum Viable Product (MVP)**.

| Feature Area | In MVP (Build Now) | Out of Scope for MVP (Defer to later) |
|  |  |  |
| **System** | Push-to-talk hotkey OR basic Wake Word. "Stop" command. | Complex conversational memory (e.g., remembering what was said 10 minutes ago). |
| **Navigation** | Open apps, Close apps, Switch active windows. | Advanced UI clicking (e.g., navigating complex web forms or drag-and-drop). |
| **Reading** | Basic document reading (extracts all text and reads it start to finish). Play/Pause functionality. | AI summarization, skipping to specific chapters, or reading image-heavy PDFs (OCR). |
| **Writing** | Basic dictation (speech-to-text typed into the active window). "Delete last word" command. | Complex text formatting (bold, italics, selecting specific sentences to rewrite). |



## 4. Why this MVP makes sense

By restricting the MVP to **Launch, Read, Dictate, and Close**, we solve 80% of a low-vision user's daily friction without requiring a massive, brittle codebase.

1. **Launch:** They can open Word.
2. **Dictate:** They can speak their thoughts onto the page.
3. **Read:** They can have the system read it back to them to check for errors.
4. **Close:** They can close the app safely.

