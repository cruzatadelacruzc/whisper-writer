# Async Whisper Model Loading — Design

**Date:** 2026-07-30
**Status:** Approved by user (brainstorming session)
**Problem:** The app loads the Whisper model synchronously inside
`initialize_components()` (src/main.py), freezing startup for ~48 s with a
warm cache and 1–3 minutes cold on the target i3-8130U. Measured breakdown
(2026-07-30, medium/int8, warm): launch→window-ready 48.06 s total, of which
`create_local_model()` itself is ~8 s — the remaining ~40 s are module
imports (`faster_whisper`/`ctranslate2`, `openai`) pulled in at import time
by `transcription.py`.

## Decisions made during brainstorming

| Question | Decision |
|----------|----------|
| UX while loading | Window appears immediately; **Start disabled** + status label ("Loading model…"); enabled with "Model ready" when done. |
| Load failure | Status label shows the error state, Start stays disabled, a QMessageBox carries the detail; recovery via the existing Settings flow (saving settings already restarts the app = natural retry). No new recovery UI. |
| Mechanism | **Approach A:** `ModelLoadThread(QThread)` with Qt signals (same pattern as the existing `ResultThread`) **plus deferring the heavy imports** into the functions that use them — async load alone would still leave a ~40 s import stall before the window shows. |

## Components

### 1. `src/model_load_thread.py` (new, ~25 lines)

```python
class ModelLoadThread(QThread):
    modelReady = pyqtSignal(object)   # emits the WhisperModel on success
    loadFailed = pyqtSignal(str)      # emits the error message on failure
```

`run()` calls `create_local_model()` inside try/except Exception and emits
exactly one of the two signals. No other responsibilities.

### 2. `src/transcription.py` (import deferral only)

- Move `from faster_whisper import WhisperModel` to the top of
  `create_local_model()` (the only place it is referenced).
- Move `from openai import OpenAI` to the top of `transcribe_api()` (the
  only place it is referenced, src/transcription.py:66-71).
- No behavioral changes; the internal CPU-fallback try/except stays as is.
- Result: `import transcription` becomes cheap; the heavy imports are paid
  inside the background thread (local mode) or on first API use.

### 3. `src/ui/main_window.py` (status label + state methods)

- New status `QLabel` under the button row; the Start button becomes an
  instance attribute so it can be toggled.
- Three methods (existing UI is English; new texts too):
  - `setModelLoading()` — label "Loading model…", Start disabled.
  - `setModelReady()` — label "Model ready", Start enabled.
  - `setModelError()` — label "Model load failed — check Settings", Start
    disabled.

### 4. `src/main.py` (wiring + guard)

- `initialize_components()`: `self.local_model = None`; build UI and show
  the window first. If `use_api` is true → `setModelReady()` immediately
  (nothing to load). Otherwise → `setModelLoading()`, create
  `self.model_load_thread` (kept as attribute so it is not GC'd), connect
  `modelReady` → `on_model_ready` (store model, `setModelReady()`),
  `loadFailed` → `on_model_load_failed` (`setModelError()`, console print,
  `QMessageBox.warning` with the message, parent = main window), then
  `start()` the thread — after `main_window.show()` so the window paints
  first.
- **Defensive guard in `start_result_thread()`:** if `self.local_model is
  None` and not `use_api`, return without starting. This blocks
  `transcribe_local()`'s silent fallback (it would synchronously load the
  model inside the recording thread). Unreachable via UI — the hotkey is
  armed only by Start, which is disabled until ready — but cheap insurance.
- Exit during load: `exit_app` does NOT wait for the load thread (waiting
  could block quit for minutes). A cosmetic Qt teardown warning
  ("QThread: Destroyed while thread is still running") is acceptable and
  verified live during implementation.

## Error handling

Any exception escaping `create_local_model()` (corrupt cache, bad config,
CPU-fallback also failing) is caught by `ModelLoadThread` and surfaces as
`loadFailed(str)` → error state + message box. The app stays alive; the user
fixes the config via Settings and saving restarts the app, which retries the
load.

## Testing (headless, following existing suite patterns)

1. `ModelLoadThread` unit tests: stub `create_local_model`; call `run()`
   directly (no real thread); assert `modelReady` fires with the stub object
   on success and `loadFailed` fires with the message on exception.
2. **Import-regression test:** in a clean interpreter, `import transcription`
   must NOT put `faster_whisper` or `openai` into `sys.modules` — protects
   the ~40 s win against future reintroduction.
3. `MainWindow` state-method tests (label text + Start enabled) under
   `QT_QPA_PLATFORM=offscreen`. If offscreen proves fragile on the CI
   runner, these tests get a documented conditional skip.
4. `start_result_thread` guard test: model `None` + local mode → returns
   without creating a ResultThread (extends the `test_main_guards` stub
   pattern).

## Live verification (merge gate)

Launch on the real desktop (`DISPLAY=:0`): window must be visible within
seconds (vs ~48 s today, warm); observe Loading → Ready transition; one real
dictation must work exactly as before once ready.

## Delivery

Through the protected flow: branch `feature/async-model-load` from
`develop` → PR to `develop` with green `tests`/`lint` checks → merge;
release PR `develop` → `main` when the user decides.

## Out of scope (YAGNI)

Load-progress percentage (faster-whisper exposes none), deferring the audio
imports (`sounddevice`/`webrtcvad` — minor cost), a ready sound, the
medium-vs-small model benchmark decision.
