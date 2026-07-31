# CLAUDE.md

## Project

WhisperWriter adapted as an "X-Ray Transcription Assistant" (Spanish medical dictation transcription; roadmap in `Plan.md`). PyQt5 desktop app with a system tray icon: records via a global hotkey and delivers the transcription into the active window — clipboard paste with automatic clipboard restore by default, typing as fallback. Every transcription is also appended to `transcription_history.txt` (gitignored, 0600, sensitive medical content). The Word/Writer export from `Plan.md` does NOT exist in the code yet.

This file describes THIS machine (Linux/X11). User-facing setup for Linux AND Windows lives in README.md.

## Commands

```bash
venv/bin/python run.py                              # run (ALWAYS from project root: it uses cwd-relative paths)
bash scripts/download_model.sh medium               # download model (resumable; watchdog restarts stalled transfers)
venv/bin/pip install -r requirements.txt -r requirements-dev.txt "setuptools<81"   # install dependencies (incl. pytest/ruff)
```

## Branch flow & CI

- `main` = stable; `develop` = integration. Both are protected by rulesets
  (`.github/rulesets/*.json`): no direct pushes, no force-push/deletion;
  changes land only via PR with the `tests` and `lint` checks green
  (0 approvals required — single-account repo, GitHub cannot self-approve).
- Work branches (`feature/...`, `fix/...`) fork from `develop` and PR back
  into `develop`; releases are a PR `develop` → `main`.
- CI: `.github/workflows/ci.yml` (Python 3.10, installs
  `requirements.txt` + `requirements-dev.txt` + `setuptools<81`).
  Run locally: `venv/bin/ruff check .` and
  `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`.
- Re-apply a ruleset after changes:
  `gh api --method POST repos/cruzatadelacruzc/whisper-writer/rulesets --input .github/rulesets/<file>.json`
  (POST creates; to modify an existing one use PUT `.../rulesets/<id>`).

## Critical environment gotchas

- Always use `venv/bin/python` (venv with Python 3.10.12), never the system Python.
- **Do NOT upgrade `setuptools`**: it must stay `<81` because setuptools 81 removed `pkg_resources` and `webrtcvad` imports it. The "pkg_resources is deprecated" warning at startup is expected and harmless.
- `venv/lib/python3.10/site-packages/gi` is a **symlink** to `/usr/lib/python3/dist-packages/gi` (system PyGObject; needed by `audioplayer`). If the venv is recreated, the symlink must be redone.
- `requirements.txt` is **UTF-16 LE with CRLF**: git treats it as binary (no line diffs); pip tolerates it (verified: also on the CI runner). Do not convert it without an explicit user decision.
- This is a GUI app: it needs a graphical session (X11, `DISPLAY=:0`). It does not start headless. The test suite, however, is fully headless.
- Native dependencies already installed on the system: `libportaudio2` (sounddevice), Qt/xcb libs, FFmpeg.
- Network: this connection reaches the HF CDN at only ~100 KB/s (parallel connections don't help — the line itself is the limit) and the hf xet backend stalls indefinitely on it. `scripts/download_model.py` sets `HF_HUB_DISABLE_XET=1`; use `scripts/download_model.sh` (watchdog) for large downloads. No proxy is configured on this machine (checked 2026-07: env, shell profiles, apt, git, pip).

## Runtime gotchas (learned the hard way)

- With `input_backend: auto` (default), the global hotkey is armed only after clicking **Start** in the main window. With an explicit `evdev`/`pynput` backend in config, it arms at startup.
- The user `cronos` is NOT in the `input` group, so the evdev backend has no accessible devices and the app falls back to `pynput` (X11 XRecord) automatically.
- Once the evdev backend has started, its signal handler **swallows SIGTERM/SIGINT** (upstream defect): the app survives `kill`. Use `kill -9` to stop a background instance reliably.
- The app's stdout is **block-buffered when redirected to a file**: prints appear only at exit. Do not poll the log for live progress; grep it after killing the process (or launch with `PYTHONUNBUFFERED=1`).
- Startup is asynchronous: the window appears within seconds with "Loading model…" and Start disabled; the Whisper model loads in a background QThread (`src/model_load_thread.py`) and the label flips to "Model ready". Heavy imports (`faster_whisper`, `openai`) are deferred into the functions that use them — reintroducing them at module level costs ~40 s of startup (pinned by `tests/test_transcription_imports.py`).

## Configuration

- User config: `src/config.yaml` — partial merge over the defaults in `src/config_schema.yaml`; only declare what changes. Current state: `model: medium`, `language: es`, `device: cpu`, `compute_type: int8`, `input_method: clipboard`, plus the anti-hallucination set (`vad_filter: true`, `condition_on_previous_text: false`, list-shaped `initial_prompt`, `min_duration: 1400`) and `recording_mode: press_to_toggle` — the rationale for each is in README "Recommended configuration".
- There is no "Spanish medium" model: `medium` is multilingual and Spanish is set via `language: es`. The `.en` variants are English-only.
- Saving from the app's Settings window **rewrites the entire `src/config.yaml`** (and restarts the app).
- Models are cached in `~/.cache/huggingface`; faster-whisper uses the `Systran/faster-whisper-*` repos. Alternatively `model_options.local.model_path` points at a plain model folder (offline installs — see README).

## Architecture

- `run.py` → loads `.env` and launches `src/main.py` (PyQt5: main window, settings, tray, `ctrl+shift+space` hotkey, async model load wiring).
- `src/transcription.py` — local faster-whisper or OpenAI API engine (`use_api: false` by default; no API keys needed). Heavy imports deferred inside the functions.
- `src/model_load_thread.py` — QThread that loads the model off the GUI thread (`modelReady`/`loadFailed` signals).
- `src/result_thread.py` — recording via sounddevice + webrtcvad.
- `src/key_listener.py` — global hotkey backends (evdev if devices accessible, else pynput).
- `src/input_simulation.py` — delivers the result: clipboard paste with deferred restore (default) or typing (pynput/ydotool/dotool).
- `src/transcription_history.py` — appends every transcription to the history file before delivery.
- `src/utils.py` — `ConfigManager` (configuration singleton).
- `tests/` — headless pytest suite (no display needed; widget tests use `QT_QPA_PLATFORM=offscreen`).
- `index.html` at the root does NOT belong to the project (accidental download); ignore it.

## Verification

Launch `venv/bin/python run.py` in the background: the window must appear within seconds ("Loading model…" → "Model ready") and the process must stay alive with no traceback. The window/tray can be verified with `DISPLAY=:0 gnome-screenshot -f <file>` (delete the capture afterwards: it contains the user's desktop). Kill test instances with `kill -9` (see runtime gotchas).

## Communication

- The user communicates in Spanish; reply in Spanish. Repo documentation (README.md, CLAUDE.md) is written in English.
