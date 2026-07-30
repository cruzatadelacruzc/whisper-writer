# CLAUDE.md

## Project

WhisperWriter adapted as an "X-Ray Transcription Assistant" (Spanish medical dictation transcription; roadmap in `Plan.md`). PyQt5 desktop app with a system tray icon: records via a global hotkey and **types** the transcription into the active window. The Word/Writer export from `Plan.md` does NOT exist in the code yet.

## Commands

```bash
venv/bin/python run.py                              # run (ALWAYS from project root: it uses cwd-relative paths)
bash scripts/download_model.sh medium               # download model (resumable; watchdog restarts stalled transfers)
venv/bin/pip install -r requirements.txt "setuptools<81"   # install dependencies
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
- `requirements.txt` is **UTF-16 LE with CRLF**: git treats it as binary (no line diffs); pip tolerates it. Do not convert it without an explicit user decision.
- This is a GUI app: it needs a graphical session (X11, `DISPLAY=:0`). It does not start headless.
- Native dependencies already installed on the system: `libportaudio2` (sounddevice), Qt/xcb libs, FFmpeg.
- Network: this connection reaches the HF CDN at only ~100 KB/s (parallel connections don't help — the line itself is the limit) and the hf xet backend stalls indefinitely on it. `scripts/download_model.py` sets `HF_HUB_DISABLE_XET=1`; use `scripts/download_model.sh` (watchdog) for large downloads. No proxy is configured on this machine (checked 2026-07: env, shell profiles, apt, git, pip).

## Configuration

- User config: `src/config.yaml` — partial merge over the defaults in `src/config_schema.yaml`; only declare what changes. Current state: `model: medium`, `language: es`, `device: cpu`, `compute_type: int8`.
- There is no "Spanish medium" model: `medium` is multilingual and Spanish is set via `language: es`. The `.en` variants are English-only.
- Saving from the app's Settings window **rewrites the entire `src/config.yaml`**.
- Models are cached in `~/.cache/huggingface`; faster-whisper uses the `Systran/faster-whisper-*` repos.

## Architecture

- `run.py` → loads `.env` and launches `src/main.py` (PyQt5: main window, settings, tray, `ctrl+shift+space` hotkey).
- `src/transcription.py` — local faster-whisper or OpenAI API engine (`use_api: false` by default; no API keys needed).
- `src/result_thread.py` — recording via sounddevice + webrtcvad.
- `src/input_simulation.py` — types the result (pynput/ydotool/dotool).
- `src/utils.py` — `ConfigManager` (configuration singleton).
- `index.html` at the root does NOT belong to the project (accidental download); ignore it.

## Verification

Launch `venv/bin/python run.py` in the background and check the process stays alive with no traceback. The window/tray can be verified with `DISPLAY=:0 gnome-screenshot -f <file>` (delete the capture afterwards: it contains the user's desktop).

## Communication

- The user communicates in Spanish; reply in Spanish. Repo documentation (README.md, CLAUDE.md) is written in English.
