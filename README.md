# X-Ray Transcription Assistant

Voice transcription assistant for radiologists, based on [WhisperWriter](https://github.com/savbell/whisper-writer). It converts medical dictations to text using a **100% local** Whisper model (faster-whisper): audio never leaves the machine, ensuring patient privacy.

**Current state:** the application delivers the transcription into whatever window is active (any editor, including an open MS Word or LibreOffice Writer document) — by default pasting it from the clipboard in one go, with automatic clipboard restore. Direct document export and the simplified clinician UI are planned in `Plan.md`.

## Requirements

### Linux

- A graphical session (tested on X11) and a microphone
- Python 3.9+ (tested with 3.10.12)
- FFmpeg (`sudo apt install ffmpeg`)
- PortAudio library (`sudo apt install libportaudio2`)
- System PyGObject/GStreamer (`sudo apt install python3-gi gir1.2-gstreamer-1.0`) — required by the `audioplayer` package
- Internet connection only if you choose the download path for the model (see [Getting the model](#getting-the-model-two-ways))

### Windows

> **Note:** Windows support comes from the upstream WhisperWriter project; the steps below have not yet been verified on this fork. If something differs on a real Windows machine, please report it.

- Windows 10/11 (64-bit) and a microphone
- [Python 3.10 (64-bit)](https://www.python.org/downloads/) — check *"Add python.exe to PATH"* during installation
- No separate FFmpeg or PortAudio installs: on Windows they come bundled inside the `av` and `sounddevice` Python wheels
- `webrtcvad` may need a C++ compiler to build — see the Windows installation note below

## Installation

### Linux

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

### Windows

From the project root, in a Command Prompt or PowerShell:

1. Create the virtual environment:

   ```bat
   py -3.10 -m venv venv
   ```

2. Install dependencies (same `setuptools` rule as on Linux):

   ```bat
   venv\Scripts\pip install -r requirements.txt "setuptools<81"
   ```

   > If the install fails while building `webrtcvad` (an error mentioning *Microsoft Visual C++* is the giveaway), either install the [Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and retry, or install the prebuilt package instead: `venv\Scripts\pip install webrtcvad-wheels` (it provides the same `webrtcvad` module).

3. There is no PyGObject step on Windows — that requirement is Linux-only.

## Getting the model (two ways)

The application uses the multilingual `medium` faster-whisper model (~1.5 GB) configured for Spanish. The model must be available locally; you can either **download** it on the target machine or **copy** it from another machine (useful for offline or slow-connection installs). If you do neither, the application downloads the model on first launch, but that in-app download is the least robust option against interruptions.

> **Note:** there is no "Spanish medium" model. `medium` is multilingual; Spanish is set via `language: es` in the configuration (already included in `src/config.yaml`). The `.en` variants (e.g. `medium.en`) are English-only — do not use them.

### Option A — Download on the target machine

**Linux (recommended):** use the included watchdog script, which is **resumable and stall-proof**: it restarts the transfer automatically if it freezes, and after a power or network outage you just run the same command again — it continues where it left off (and finishes instantly if already complete). On slow connections it can take hours: leave it running, it takes care of itself.

```bash
bash scripts/download_model.sh medium
```

**Windows (or any OS):** the watchdog wrapper is Linux-only, but the underlying downloader is plain Python and works everywhere. It is resumable too — if it is interrupted, run the same command again and it continues:

```bat
venv\Scripts\python scripts\download_model.py medium
```

Either way the model lands in the HuggingFace cache (see paths below), where the application finds it automatically.

### Option B — Copy the model files from another machine (offline install)

Both variants start the same way: on a machine that already has the model (a **completed** download — never copy a partial one), locate the HuggingFace cache folder:

| OS | Cache folder |
|---|---|
| Linux | `~/.cache/huggingface/hub/` |
| Windows | `%USERPROFILE%\.cache\huggingface\hub\` |

Inside it, the model is the folder `models--Systran--faster-whisper-medium`.

**B1 — Copy into the target's cache (zero configuration).** Copy that entire folder — keeping its internal structure (`blobs/`, `refs/`, `snapshots/`) intact — into the same cache location on the target machine, creating the directories if they do not exist yet. The application finds it automatically; nothing to configure. This works across operating systems (Linux → Windows and vice versa).

> On Linux, the files under `snapshots/` are symlinks into `blobs/` — copy the folder as-is (e.g. `cp -a`, or zip/unzip it) so the links survive, or use `cp -rL` on just the snapshot to resolve them.

**B2 — Plain folder anywhere + `model_path` (no cache involved).** Copy the *contents* of the snapshot folder (`models--Systran--faster-whisper-medium/snapshots/<hash>/` — the files `model.bin`, `config.json`, `tokenizer.json`, `vocabulary.txt`; resolve symlinks when copying, e.g. `cp -rL`) into any folder you like — a USB stick, a shared drive, `D:\models\faster-whisper-medium`, etc. Then point the configuration at it in `src/config.yaml`:

```yaml
model_options:
  local:
    model_path: /media/usb/faster-whisper-medium   # or e.g. D:\models\faster-whisper-medium
```

With `model_path` set, the application loads the model from that folder and never attempts a download.

## Running

From the project root:

**Linux:**

```bash
venv/bin/python run.py
```

(or `source venv/bin/activate && python run.py`)

**Windows:**

```bat
venv\Scripts\python run.py
```

It must be run **from the project root** on both systems.

- The main window appears within a few seconds showing **“Loading model…”** with the Start button disabled; when the label changes to **“Model ready”**, Start is enabled and you can begin dictating. If loading fails, the label shows *“Model load failed — check Settings”* — fix the model configuration in Settings (saving restarts the application, which retries the load).
- The application sits as a system tray icon.
- Dictation hotkey: **`ctrl+shift+space`** (configurable). **Clicking Start behaves exactly like pressing the hotkey**: it arms the hotkey and starts recording immediately (the status overlay appears and the window hides). Later recordings are started and stopped with the hotkey.
- The `pkg_resources is deprecated` warning at startup is harmless: ignore it.
- The main window (tray icon → WhisperWriter Main Menu) has three buttons: **Start** (arm the hotkey and start recording — a click behaves like a hotkey press), **Settings** (open the Settings window), and **Copy Last** (re-copy the most recent transcription to the clipboard, in case the original paste was missed or overwritten), plus the model status label described above.

## The dictation flow, step by step

1. Wait for **Model ready**, press **Start** — recording begins immediately and the window hides. Focus the target document while you speak: the text lands in the **active** window when transcription finishes.
2. Speak one phrase. How recording stops depends on `recording_options.recording_mode` (table below): with the recommended `press_to_toggle` you press the hotkey when the phrase is done; the VAD-based modes (`continuous`, `voice_activity_detection`) stop on their own after ~0.9 s of silence (`recording_options.silence_duration`).
3. The overlay shows *transcribing* and the text is pasted into the active window. For the next phrase press **`ctrl+shift+space`** — the hotkey stays armed.
4. What happens next depends on `recording_options.recording_mode`:

| `recording_mode` | After each phrase | Best for |
|---|---|---|
| `press_to_toggle` *(project recommendation)* | Recording **stops**; press the hotkey again for the next phrase. Pressing the hotkey mid-recording stops it manually. | Dictating discrete report sentences with pauses to think — no accidental recordings between phrases. |
| `continuous` *(upstream default)* | The app **keeps listening** and auto-starts a new recording at the next voice activity, until you press the hotkey again to stop the cycle. | Dictating long passages hands-free. Caveat: ambient noise can trigger phantom recordings between real phrases — see the recommended configuration below. |
| `voice_activity_detection` | Like a single-shot `continuous`: one recording, stops at silence, done. | One-off dictations. |
| `hold_to_record` | Records only while the hotkey is held down. | Walkie-talkie style, full manual control. |

## Recommended configuration (Spanish medical dictation)

The configuration this project converged on after live testing on real radiology dictation — each line exists for a reason:

```yaml
model_options:
  common:
    language: es
    # Vocabulary list (not a sentence): biases Whisper toward radiology terms.
    # Keep it a list — a sentence-shaped prompt can be echoed verbatim into
    # near-silent recordings and end up pasted as if dictated.
    initial_prompt: "Radiografía de tórax, silueta cardiomediastínica, trama broncovascular, consolidación, derrame pleural, neumotórax, campos pulmonares, estructuras óseas, impresión diagnóstica."
  local:
    model: medium       # small is noticeably worse on Spanish medical terms
    device: cpu
    compute_type: int8
    # Anti-hallucination pair: without these, trailing/ambient silence gets
    # transcribed as YouTube-subtitle credits ("Subtítulos por la comunidad
    # de Amara.org", "¡Gracias por ver el vídeo!").
    vad_filter: true
    condition_on_previous_text: false
recording_options:
  recording_mode: press_to_toggle
  # Phantom VAD triggers from ambient noise last ~1.2 s (noise + the 0.9 s
  # silence tail); discard anything shorter before transcribing.
  min_duration: 1400
post_processing:
  input_method: clipboard
```

Notes:

- `medium` is the accuracy/speed sweet spot for clinical Spanish on CPU; transcription takes roughly the duration of the phrase on an older i3-class machine. `small` halves the wait but garbles medical terms (*"tórax" → "tólas"* in our tests) — only worth it on very weak hardware and non-critical text.
- If you prefer hands-free flow, switch `recording_mode` to `continuous`; `min_duration`, `vad_filter` and the list-shaped prompt above are what keep phantom recordings and hallucinated text in check in that mode.
- All of this can also be changed from the Settings window (saving restarts the app).

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

(Add `model_path` under `local` only if you provisioned the model as a plain folder — see Option B2 above.)

It can also be edited from the application's Settings window (tray icon → Open Settings). Saving from the UI rewrites the entire `src/config.yaml`.

**Input method:** `post_processing.input_method` controls how the transcribed text is delivered to the active window. The project default is `clipboard`: the whole transcription is copied to the clipboard and pasted at once with a simulated Ctrl+V, which is fast and avoids issues with special characters. Your previous clipboard is not lost: it is restored automatically about a second after the paste, and the restore preserves the full clipboard content, including non-text formats such as a copied image. If clipboard access fails, the app automatically falls back to typing the text character by character. If the paste keystroke itself fails after the clipboard was already prepared, no fallback is attempted (to avoid double-delivery) — the transcription is still recoverable from `transcription_history.txt`. The other supported values (`pynput`, `ydotool`, `dotool`) always type character by character and can be selected instead from the Settings window if pasting is not desired (`ydotool`/`dotool` are Linux-only).

> **Note:** the clipboard method sends a plain Ctrl+V, so it targets regular editors (MS Word, LibreOffice Writer, text fields, etc.). Terminal emulators paste with Ctrl+Shift+V, so dictating into a terminal will not paste — use one of the typing methods (`pynput`, `ydotool`, `dotool`) there.

**Transcription history:** every dictation (regardless of input method) is appended to `transcription_history.txt` in the project root before it is delivered to the active window, each entry prefixed with a timestamp. This is a power-cut/crash safeguard: if the target application never received the paste/keystrokes, or the machine loses power right after a dictation, the transcribed text is not lost — it can be recovered from this plain-text file. The file grows indefinitely (it is never rotated or cleared automatically); it may contain sensitive dictated content, so it is created with owner-only permissions (`0600` on Linux) and should be handled accordingly.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named 'pkg_resources'` | `setuptools` ≥ 81 in the venv | `venv/bin/pip install "setuptools<81"` (Windows: `venv\Scripts\pip …`) |
| `No module named 'gi'` (Linux) | Missing PyGObject link in the venv | Redo the symlink from Linux installation step 3 |
| `PortAudio library not found` (Linux) | Missing native audio library | `sudo apt install libportaudio2` |
| `Could not load the Qt platform plugin "xcb"` (Linux) | Missing native Qt libraries | `sudo apt install libxcb-xinerama0 libxkbcommon-x11-0` |
| `webrtcvad` fails to install (Windows) | Source-only package, needs a C++ compiler | Install the MS C++ Build Tools, or `pip install webrtcvad-wheels` |
| Model download interrupted or frozen | Power/network outage, unstable connection | Re-run the download command (both scripts resume; the `.sh` also auto-restarts stalls) |
| Stuck on “Loading model…” then *Model load failed* on an offline machine | Model files missing or in the wrong place | Check the cache path for your OS (see Option B1) or set `model_path` (Option B2) |
| App does not react to the hotkey (Linux) | Wayland session or keyboard permissions | Use an X11 session; check `recording_options.input_backend` (without membership in the `input` group, the app falls back to the `pynput` backend automatically) |
| App does not react to the hotkey (Windows) | — | The `pynput` backend is used automatically on Windows; make sure you pressed **Start** and the label says *Model ready* |

> **Warning:** do not upgrade `setuptools` in the venv (e.g. with `pip install -U setuptools`); the `pkg_resources` error would come back.
