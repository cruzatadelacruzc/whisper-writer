# X-Ray Transcription Assistant

Voice transcription assistant for radiologists, based on [WhisperWriter](https://github.com/savbell/whisper-writer). It converts medical dictations to text using a **100% local** Whisper model (faster-whisper): audio never leaves the machine, ensuring patient privacy.

**Current state:** the application types the transcription into whatever window is active (any editor, including an open MS Word or LibreOffice Writer document). Direct document export and the simplified clinician UI are planned in `Plan.md`.

## Requirements

- Linux with a graphical session (tested on X11) and a microphone
- Python 3.9+ (tested with 3.10.12)
- FFmpeg (`sudo apt install ffmpeg`)
- PortAudio library (`sudo apt install libportaudio2`)
- System PyGObject/GStreamer (`sudo apt install python3-gi gir1.2-gstreamer-1.0`) — required by the `audioplayer` package
- Internet connection only for the initial model download

## Installation

From the project root:

1. Create the virtual environment:

   ```bash
   python3 -m venv venv
   ```

2. Install dependencies. **Important:** `setuptools` must stay below version 81, because `webrtcvad` still needs `pkg_resources` (removed in setuptools 81):

   ```bash
   venv/bin/pip install -r requirements.txt "setuptools<81"
   ```

3. Link the system PyGObject into the venv (the `audioplayer` package needs it and it is not pip-installable here):

   ```bash
   ln -s /usr/lib/python3/dist-packages/gi venv/lib/python3.10/site-packages/gi
   ```

   > Adjust `python3.10` if your venv uses a different version (it must match the system Python).

## Model download (recommended before first use)

The project uses the multilingual `medium` model configured for Spanish. Download it with the included watchdog script, which is **resumable and stall-proof**: it restarts the transfer automatically if it freezes, and after a power or network outage you just run the same command again — it continues where it left off (and finishes instantly if already complete):

```bash
bash scripts/download_model.sh medium
```

The download is ~1.5 GB and lands in `~/.cache/huggingface`, where the application finds it automatically. On slow connections it can take hours: leave it running, it takes care of itself. If you skip this step, the application downloads the model on first launch, but that in-app download is less robust against interruptions — hence the script. (`scripts/download_model.py` is the underlying single-attempt downloader, also resumable.)

> **Note:** there is no "Spanish medium" model. `medium` is multilingual; Spanish is set via `language: es` in the configuration (already included in `src/config.yaml`). The `.en` variants (e.g. `medium.en`) are English-only — do not use them.

## Running

```bash
venv/bin/python run.py
```

(or `source venv/bin/activate && python run.py`). It must be run **from the project root**.

- The application sits as a system tray icon.
- Dictation hotkey: **`ctrl+shift+space`** (configurable).
- The first transcription takes longer because the model is loaded into memory.
- The `pkg_resources is deprecated` warning at startup is harmless: ignore it.
- The main window (tray icon → WhisperWriter Main Menu) has three buttons: **Start** (begin a dictation), **Settings** (open the Settings window), and **Copy Last** (re-copy the most recent transcription to the clipboard, in case the original paste was missed or overwritten).

## Configuration

User configuration lives in `src/config.yaml` and only needs the keys that differ from the defaults (`src/config_schema.yaml`). The project's current configuration:

```yaml
model_options:
  common:
    language: es        # transcribe in Spanish
  local:
    model: medium       # multilingual medium model
    device: cpu
    compute_type: int8  # faster and lighter on CPU
post_processing:
  input_method: clipboard  # paste the whole text at once (see below)
```

It can also be edited from the application's Settings window (tray icon → Open Settings). Saving from the UI rewrites the entire `src/config.yaml`.

**Input method:** `post_processing.input_method` controls how the transcribed text is delivered to the active window. The project default is `clipboard`: the whole transcription is copied to the clipboard and pasted at once with a simulated Ctrl+V, which is fast and avoids issues with special characters. If clipboard access fails, or the input backend does not support the paste shortcut, the app automatically falls back to typing the text character by character. The other supported values (`pynput`, `ydotool`, `dotool`) always type character by character and can be selected instead from the Settings window if pasting is not desired.

**Transcription history:** every dictation (regardless of input method) is appended to `transcription_history.txt` in the project root before it is delivered to the active window, each entry prefixed with a timestamp. This is a power-cut/crash safeguard: if the target application never received the paste/keystrokes, or the machine loses power right after a dictation, the transcribed text is not lost — it can be recovered from this plain-text file. The file grows indefinitely (it is never rotated or cleared automatically); it may contain sensitive dictated content, so handle it accordingly.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named 'pkg_resources'` | `setuptools` ≥ 81 in the venv | `venv/bin/pip install "setuptools<81"` |
| `No module named 'gi'` | Missing PyGObject link in the venv | Redo the symlink from installation step 3 |
| `PortAudio library not found` | Missing native audio library | `sudo apt install libportaudio2` |
| `Could not load the Qt platform plugin "xcb"` | Missing native Qt libraries | `sudo apt install libxcb-xinerama0 libxkbcommon-x11-0` |
| Model download interrupted or frozen | Power/network outage, unstable connection | Re-run `bash scripts/download_model.sh medium` (it resumes and auto-restarts stalls) |
| App does not react to the hotkey | Wayland session or keyboard permissions | Use an X11 session; check `recording_options.input_backend` |

> **Warning:** do not upgrade `setuptools` in the venv (e.g. with `pip install -U setuptools`); the `pkg_resources` error would come back.
