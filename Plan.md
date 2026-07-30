# X-Ray Transcription Assistant - Development Plan

## Objective

Develop a local, privacy-focused transcription tool for X-ray specialists. It uses a local Whisper model (faster-whisper, CPU, int8) to convert Spanish medical dictations into text, featuring a simple GUI and reliable text delivery into Word/LibreOffice documents.

**Target hardware:** Intel i3-8130U (2 cores + HT, 2.2 GHz), 11 GB RAM, CPU-only.
**Target platform:** not decided yet (Windows hospital machines vs. Linux) — platform-specific work is deferred until this is settled; the core stack (PyQt5, sounddevice, faster-whisper, pynput) is cross-platform.

---

## Phase 1: Environment & Codebase Integration — ✅ DONE (2026-07-29)

- [x] Merge cloned `whisper-writer` contents into the existing project repository.
- [x] Set up Python virtual environment (`venv`, Python 3.10.12).
- [x] Install dependencies (see README.md for the environment gotchas: `setuptools<81`, system `gi` symlink).
- [x] Configure default settings: `model="medium"`, `language="es"`, `device="cpu"`, `compute_type="int8"` (`src/config.yaml`).
- [x] Verify initial execution (app launches; settings window + tray icon work).
- [ ] Finish model download — in progress via `bash scripts/download_model.sh medium` (resumable watchdog; survives power/network cuts).

## Phase 2: Core Transcription Engine

- [ ] **Benchmark gate:** time a real Spanish dictation with `medium` int8 on the i3-8130U. If slower than ~1.5× real time, download `small` (~460 MB) and compare speed and medical-term accuracy before choosing the default model.
  - Note: faster-whisper/CTranslate2 does not support int4 — int8 is its floor. Switching to whisper.cpp (q4/q5) is plan C only if `small` int8 is still too slow.
- [ ] Add `initial_prompt` with Spanish radiology vocabulary to improve domain-term accuracy (config option already exists).
- [ ] Add error handling for audio device failures and model loading issues.

## Phase 3: Robust Output (priority)

- [ ] **Clipboard injection:** new `input_method: clipboard` — copy the transcription and simulate Ctrl+V so the full text appears at once in Word/Writer, instead of being typed character by character. Preserve and restore the user's previous clipboard. Keep current typing method as fallback.
- [ ] **Transcription history:** append every transcription (with timestamp) to a local text file, so a power cut or crash never loses a dictated report.
- [ ] Manual "Copy to Clipboard" button.

## Phase 4: UI/UX Refinement for Clinicians

- [ ] Simplify the PyQt5 interface (minimalist design, large buttons, clear status indicators).
- [ ] Add visual feedback: "Listening...", "Processing...", "Ready".
- [ ] Verify global hotkey reliability (`Ctrl+Shift+Space` toggle).

## Phase 5: Testing, Optimization & Deployment

- [ ] Performance testing on the real target hardware (i3-8130U, RAM monitoring alongside typical workloads like a browser).
- [ ] Stress test with continuous dictation sessions (15+ minutes).
- [ ] **Decide target platform** (Windows vs. Linux), then package accordingly (`PyInstaller` or `Nuitka`).
- [ ] Draft a concise user manual for hospital staff.

---

## Future ideas (out of scope for now)

- **Transcribe audio file:** open a pre-recorded dictation (wav/mp3) and transcribe it. This replaces the old "Windows Loopback / VB-Audio Virtual Cable" idea with a simpler, cross-platform solution for the same need.
- **whisper.cpp engine (int4/q5):** only as plan C if `small` int8 proves too slow on the target hardware.

## Next Immediate Step

Wait for the `medium` download to finish (watchdog running), launch the app, and run the Phase 2 benchmark: a timed Spanish dictation to decide between `medium` and `small`.
