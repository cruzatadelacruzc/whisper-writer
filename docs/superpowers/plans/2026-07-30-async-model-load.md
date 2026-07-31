# Async Whisper Model Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the main window within seconds of launch and load the Whisper model in a background QThread with visible state (Loading → Ready / Error), instead of freezing startup for ~48 s–3 min.

**Architecture:** A new `ModelLoadThread(QThread)` (same pattern as the existing `ResultThread`) runs `create_local_model()` off the GUI thread and reports via `modelReady(object)` / `loadFailed(str)` signals. The heavy imports (`faster_whisper`, `openai`) move from module level into the functions that use them, so `import transcription` becomes cheap and the ~40 s import cost is paid inside the background thread. `MainWindow` gains a status label and three state methods; `main.py` wires the signals and guards `start_result_thread` against a not-yet-loaded model.

**Tech Stack:** PyQt5 (QThread, pyqtSignal, QLabel, QMessageBox), faster-whisper, pytest (headless; `QT_QPA_PLATFORM=offscreen` where widgets are needed).

**Spec:** `docs/superpowers/specs/2026-07-30-async-model-load-design.md`

## Global Constraints

- Branch: `feature/async-model-load` from up-to-date `develop`. The repo flow is protected: NO direct pushes to `develop`/`main`; delivery is PR → checks `tests`+`lint` green → merge.
- Local commands use `venv/bin/python` / `venv/bin/pip` / `venv/bin/ruff` from the project root; test suite runs headless: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`. Current suite: 19 passed — must stay green and grow.
- `venv/bin/ruff check .` must stay clean (CI `lint` job blocks otherwise). If an edit orphans an import (e.g. `create_local_model` in main.py), remove it.
- UI text exact values (existing UI is English): `Loading model…`, `Model ready`, `Model load failed — check Settings`.
- Never commit `src/config.yaml` or `index.html`. Never use `git add -A`/`git add .` — add exact paths.
- Every commit message ends with the trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- The GUI app itself needs `DISPLAY=:0`; screenshots of the desktop must be deleted after checking (they show the user's screen).

---

### Task 1: Branch, docs commit, and import deferral (TDD)

**Files:**
- Commit (already on disk, untracked): `docs/superpowers/specs/2026-07-30-async-model-load-design.md`, `docs/superpowers/plans/2026-07-30-async-model-load.md`
- Modify: `src/transcription.py` (lines 1-8 imports; `create_local_model`; `transcribe_api`)
- Test: `tests/test_transcription_imports.py` (new)

**Interfaces:**
- Consumes: current `src/transcription.py` — module-level `from faster_whisper import WhisperModel` (line 5) and `from openai import OpenAI` (line 6).
- Produces: cheap `import transcription`; `create_local_model()` signature unchanged (Task 2 calls it); `transcribe_api()` behavior unchanged.

- [ ] **Step 1: Create the branch and commit the docs**

```bash
git checkout develop && git pull
git checkout -b feature/async-model-load
git add docs/superpowers/specs/2026-07-30-async-model-load-design.md docs/superpowers/plans/2026-07-30-async-model-load.md
git commit -m "docs: add async model load design spec and implementation plan

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 2: Write the failing import-regression test**

Create `tests/test_transcription_imports.py`:

```python
"""import transcription must stay cheap: the heavy libraries are deferred
into the functions that use them (spec: async-model-load). A module-level
reimport of faster_whisper/openai would put ~40s back on the startup path,
so this is checked in a CLEAN subprocess interpreter, not in-process."""
import os
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

CHECK = (
    "import sys, os;"
    "sys.path.insert(0, os.path.join(%r, 'src'));"
    "import transcription;"
    "assert 'faster_whisper' not in sys.modules, 'faster_whisper imported at module level';"
    "assert 'openai' not in sys.modules, 'openai imported at module level';"
    "print('DEFERRED_OK')"
) % (PROJECT_ROOT,)


def test_importing_transcription_does_not_pull_heavy_libraries():
    result = subprocess.run(
        [sys.executable, '-c', CHECK],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert 'DEFERRED_OK' in result.stdout
```

- [ ] **Step 3: Run it to verify it fails (RED)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_transcription_imports.py -v`
Expected: FAIL — the assert message `faster_whisper imported at module level` appears in stderr (both libraries are currently imported at `src/transcription.py:5-6`).

- [ ] **Step 4: Move the imports into their functions**

In `src/transcription.py`:
1. Delete lines 5-6 (`from faster_whisper import WhisperModel` and `from openai import OpenAI`).
2. Add as the FIRST line inside `def create_local_model():` (before the docstring stays fine after it — put the import right after the docstring):
```python
    from faster_whisper import WhisperModel  # deferred: heavy import paid in the loader thread
```
3. Add right after the docstring of `def transcribe_api(audio_data):`:
```python
    from openai import OpenAI  # deferred: only needed in API mode
```
No other changes — the internal try/except CPU fallback in `create_local_model` stays as is.

- [ ] **Step 5: Run the test to verify it passes (GREEN)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_transcription_imports.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite + ruff**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/ && venv/bin/ruff check .`
Expected: `20 passed`, `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/transcription.py tests/test_transcription_imports.py
git commit -m "perf: defer faster_whisper/openai imports out of the startup path

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: ModelLoadThread (TDD)

**Files:**
- Create: `src/model_load_thread.py`
- Test: `tests/test_model_load_thread.py` (new)

**Interfaces:**
- Consumes: `create_local_model()` from Task 1 (imported at module level of the new file — cheap after Task 1).
- Produces: `class ModelLoadThread(QThread)` with signals `modelReady = pyqtSignal(object)` and `loadFailed = pyqtSignal(str)`; `run()` emits exactly one of them. Task 4 instantiates it, connects both signals, and calls `.start()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_model_load_thread.py`:

```python
"""ModelLoadThread unit tests. run() is called directly (no real thread,
no QApplication, no event loop): pyqtSignal delivers synchronously to
directly-connected Python callables."""
import os
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_model_ready_emitted_with_the_loaded_model():
    import model_load_thread
    fake_model = object()
    received = []
    thread = model_load_thread.ModelLoadThread()
    thread.modelReady.connect(received.append)
    thread.loadFailed.connect(lambda msg: received.append(('FAILED', msg)))
    with patch.object(model_load_thread, 'create_local_model', return_value=fake_model):
        thread.run()
    assert received == [fake_model]


def test_load_failed_emitted_with_the_error_message():
    import model_load_thread
    received = []
    thread = model_load_thread.ModelLoadThread()
    thread.modelReady.connect(lambda m: received.append(('READY', m)))
    thread.loadFailed.connect(received.append)
    with patch.object(model_load_thread, 'create_local_model',
                      side_effect=RuntimeError('corrupt cache')):
        thread.run()
    assert received == ['corrupt cache']
```

- [ ] **Step 2: Run them to verify they fail (RED)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_model_load_thread.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'model_load_thread'`.

- [ ] **Step 3: Write the implementation**

Create `src/model_load_thread.py`:

```python
from PyQt5.QtCore import QThread, pyqtSignal

from transcription import create_local_model


class ModelLoadThread(QThread):
    """
    Load the Whisper model off the GUI thread so the window stays
    responsive during the 8s-3min create_local_model() call.
    """
    modelReady = pyqtSignal(object)
    loadFailed = pyqtSignal(str)

    def run(self):
        try:
            model = create_local_model()
        except Exception as e:
            self.loadFailed.emit(str(e))
        else:
            self.modelReady.emit(model)
```

- [ ] **Step 4: Run the tests to verify they pass (GREEN)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_model_load_thread.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Full suite + ruff**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/ && venv/bin/ruff check .`
Expected: `22 passed`, `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/model_load_thread.py tests/test_model_load_thread.py
git commit -m "feat: add ModelLoadThread to load Whisper off the GUI thread

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: MainWindow status label and state methods (TDD)

**Files:**
- Modify: `src/ui/main_window.py`
- Test: `tests/test_main_window_states.py` (new)

**Interfaces:**
- Consumes: existing `MainWindow(BaseWindow)` with `initMainUI()` building three 120x60 buttons in a `QHBoxLayout` wrapped by two `addStretch(1)` calls on `self.main_layout`.
- Produces: `self.start_btn` (the Start QPushButton as an attribute), `self.model_status_label` (QLabel), and methods `setModelLoading()`, `setModelReady()`, `setModelError()` — Task 4 calls exactly these three names.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_main_window_states.py`:

```python
"""MainWindow model-state methods. Needs real widgets, so a QApplication is
created on the offscreen platform. If the platform cannot initialize in this
environment (spec allows it), the module is skipped — the states are also
exercised live during verification."""
import os
import sys

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
except Exception as e:  # offscreen platform unavailable
    pytest.skip(f'offscreen QApplication unavailable: {e}', allow_module_level=True)


@pytest.fixture()
def window():
    from ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_set_model_loading_disables_start(window):
    window.setModelLoading()
    assert window.model_status_label.text() == 'Loading model…'
    assert window.start_btn.isEnabled() is False


def test_set_model_ready_enables_start(window):
    window.setModelLoading()
    window.setModelReady()
    assert window.model_status_label.text() == 'Model ready'
    assert window.start_btn.isEnabled() is True


def test_set_model_error_disables_start(window):
    window.setModelReady()
    window.setModelError()
    assert window.model_status_label.text() == 'Model load failed — check Settings'
    assert window.start_btn.isEnabled() is False
```

- [ ] **Step 2: Run them to verify they fail (RED)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_window_states.py -v`
Expected: FAIL with `AttributeError` (`setModelLoading` / `model_status_label` do not exist). If instead the module SKIPS with "offscreen QApplication unavailable", stop and report it — the implementation can proceed but say so in your report.

- [ ] **Step 3: Implement the label and methods**

In `src/ui/main_window.py`:

1. Extend imports:
```python
from PyQt5.QtWidgets import QApplication, QPushButton, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal
```
2. In `initMainUI()`, make Start an attribute — replace the three `start_btn` references with `self.start_btn`:
```python
        self.start_btn = QPushButton('Start')
        self.start_btn.setFont(QFont('Segoe UI', 10))
        self.start_btn.setFixedSize(120, 60)
        self.start_btn.clicked.connect(self.startPressed)
```
(and `button_layout.addWidget(self.start_btn)` below.)
3. Still in `initMainUI()`, create the status label and insert it under the button row — the layout block becomes:
```python
        self.model_status_label = QLabel('')
        self.model_status_label.setFont(QFont('Segoe UI', 10))
        self.model_status_label.setAlignment(Qt.AlignCenter)
        self.model_status_label.setStyleSheet('color: #404040;')

        self.main_layout.addStretch(1)
        self.main_layout.addLayout(button_layout)
        self.main_layout.addWidget(self.model_status_label)
        self.main_layout.addStretch(1)
```
4. Add the three state methods after `startPressed`:
```python
    def setModelLoading(self):
        """Model is loading in the background: block Start, show progress text."""
        self.model_status_label.setText('Loading model…')
        self.start_btn.setEnabled(False)

    def setModelReady(self):
        """Model (or API mode) is ready: allow Start."""
        self.model_status_label.setText('Model ready')
        self.start_btn.setEnabled(True)

    def setModelError(self):
        """Model load failed: keep Start blocked; Settings is the way out."""
        self.model_status_label.setText('Model load failed — check Settings')
        self.start_btn.setEnabled(False)
```

- [ ] **Step 4: Run the tests to verify they pass (GREEN)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_window_states.py -v`
Expected: 3 PASS (or module SKIP only if Step 2 already skipped — then rely on Task 5 live verification and say so in the report).

- [ ] **Step 5: Full suite + ruff**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/ && venv/bin/ruff check .`
Expected: `25 passed` (or 22 passed + 3 skipped), `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/ui/main_window.py tests/test_main_window_states.py
git commit -m "feat: add model-state label and Start gating to the main window

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Wire the async load in main.py + guard (TDD for the guard)

**Files:**
- Modify: `src/main.py` (`initialize_components`, `start_result_thread`, new slots)
- Test: `tests/test_main_guards.py` (extend — follow the file's existing stub-and-unbound-method pattern)

**Interfaces:**
- Consumes: `ModelLoadThread` (Task 2: signals `modelReady(object)`, `loadFailed(str)`); `MainWindow.setModelLoading()/setModelReady()/setModelError()` (Task 3).
- Produces: `WhisperWriterApp.on_model_ready(model)` and `on_model_load_failed(message)` slots; `self.use_api` (bool) and `self.model_load_thread` attributes; guarded `start_result_thread`.

- [ ] **Step 1: Write the failing guard test**

Append to `tests/test_main_guards.py`, reusing the module's existing stub installation and `main` import pattern (read the file first; it stubs `audioplayer`/`pynput`/heavy deps in `sys.modules` and exercises methods as unbound functions over a `MagicMock` self):

```python
def test_start_result_thread_returns_early_when_model_not_loaded():
    """Local mode with the model still loading: start_result_thread must not
    build a ResultThread (transcribe_local would otherwise sync-load the
    model inside the recording thread)."""
    main = _get_main_module()
    self_mock = MagicMock()
    self_mock.result_thread = None
    self_mock.local_model = None
    self_mock.use_api = False
    with patch.object(main, 'ResultThread') as result_thread_cls:
        main.WhisperWriterApp.start_result_thread(self_mock)
    result_thread_cls.assert_not_called()
```

If the file's helper for importing `main` has a different name than `_get_main_module`, use the file's actual helper — the test body stays the same. If no such helper exists, mirror how the existing tests in that file import `main` after installing stubs.

- [ ] **Step 2: Run it to verify it fails (RED)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_guards.py -v`
Expected: the new test FAILS (`ResultThread` was called — no guard exists yet); the pre-existing tests still pass.

- [ ] **Step 3: Implement the wiring and the guard**

In `src/main.py`:

1. Replace the import `from transcription import create_local_model` with:
```python
from model_load_thread import ModelLoadThread
```
(`create_local_model` is no longer referenced from main.py; leaving the import would fail ruff F401.)
2. In `initialize_components()`, replace the model-loading lines:
```python
        model_options = ConfigManager.get_config_section('model_options')
        self.local_model = create_local_model() if not model_options.get('use_api') else None
```
with:
```python
        model_options = ConfigManager.get_config_section('model_options')
        self.use_api = bool(model_options.get('use_api'))
        self.local_model = None
        self.model_load_thread = None
```
3. At the END of `initialize_components()`, after `self.main_window.show()`, start the load (window paints first; the thread object is kept as an attribute so it is not garbage-collected):
```python
        if self.use_api:
            self.main_window.setModelReady()
        else:
            self.main_window.setModelLoading()
            self.model_load_thread = ModelLoadThread()
            self.model_load_thread.modelReady.connect(self.on_model_ready)
            self.model_load_thread.loadFailed.connect(self.on_model_load_failed)
            self.model_load_thread.start()
```
4. Add the two slots after `initialize_components` (QMessageBox is already imported in main.py):
```python
    def on_model_ready(self, model):
        """The background loader finished: store the model and unlock Start."""
        self.local_model = model
        self.main_window.setModelReady()

    def on_model_load_failed(self, message):
        """Loading failed: surface the error and leave Start blocked.
        Recovery path: fix Settings — saving restarts the app, retrying the load."""
        print(f'Model load failed: {message}')
        self.main_window.setModelError()
        QMessageBox.warning(self.main_window, 'WhisperWriter',
                            f'Could not load the Whisper model:\n{message}')
```
5. In `start_result_thread()`, add the guard right after the existing `isRunning` early-return:
```python
        # The hotkey is only armed via Start (disabled until the model is
        # ready), but guard anyway: ResultThread with local_model=None would
        # sync-load the model inside the recording thread.
        if self.local_model is None and not self.use_api:
            return
```
6. `exit_app` stays unchanged: it does NOT wait for `model_load_thread` (spec decision — waiting could block quit for minutes; a cosmetic Qt teardown warning is acceptable and gets checked live in Task 5).

- [ ] **Step 4: Run the guard test to verify it passes (GREEN)**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_guards.py -v`
Expected: all PASS including the new test.

- [ ] **Step 5: Full suite + ruff**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/ && venv/bin/ruff check .`
Expected: `26 passed` (25 + new guard test; or with Task 3 skips: 23 passed + 3 skipped), `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_guards.py
git commit -m "feat: load the Whisper model asynchronously at startup

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Live verification and setup PR (stops for the user's dictation gate)

**Files:**
- No code changes expected (fix-iterate on the branch only if verification or CI finds a defect).

**Interfaces:**
- Consumes: the complete branch (Tasks 1-4).
- Produces: empirical startup-time evidence; an open PR to `develop` with green checks, ready for the user's live-dictation merge gate.

- [ ] **Step 1: Launch the app and time the window**

```bash
SCRATCH=/tmp/claude-1000/-mnt-D4B873F1B873D10A-Dev-Python-whisper-writer/aba5318a-aa21-484f-aec9-983211dd7627/scratchpad
date +%s.%N > "$SCRATCH/t0"
DISPLAY=:0 venv/bin/python run.py > "$SCRATCH/async-smoke.log" 2>&1 &
APP_PID=$!
sleep 12
DISPLAY=:0 gnome-screenshot -f "$SCRATCH/shot-12s.png"
```
Read the screenshot: the WhisperWriter window must ALREADY be visible, showing `Loading model…` (or `Model ready` if the load beat 12 s) with Start visually disabled. Window visible at 12 s vs the old ~48 s = the measurable win.

- [ ] **Step 2: Verify the Ready transition**

```bash
sleep 50
DISPLAY=:0 gnome-screenshot -f "$SCRATCH/shot-62s.png"
```
Read the screenshot: label `Model ready`, Start enabled. (Warm-cache load is ~8-15 s on this machine; 62 s is generous margin.)

- [ ] **Step 3: Clean shutdown check**

```bash
kill -9 "$APP_PID"
grep -ci "traceback" "$SCRATCH/async-smoke.log" || echo NO_TRACEBACK
rm -f "$SCRATCH"/shot-12s.png "$SCRATCH"/shot-62s.png
```
Expected: `NO_TRACEBACK`. The screenshots MUST be deleted (they capture the user's desktop). Note in the report whether the log shows `Creating local model...` appearing (it should — printed from the loader thread).

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feature/async-model-load
gh pr create --base develop --head feature/async-model-load \
  --title "feat: async Whisper model load with visual startup feedback" \
  --body "$(cat <<'EOF'
## Summary
- Window shows within seconds; the Whisper model loads in a background QThread (`ModelLoadThread`)
- Heavy imports (faster_whisper, openai) deferred out of the startup path (~40s saved before window paint)
- Main window gains a status label (Loading model… / Model ready / Model load failed — check Settings) and Start stays disabled until ready
- Guard: start_result_thread refuses to run while the model is not loaded (blocks the transcribe_local sync-load fallback)

## Test plan
- 4 new headless tests (loader signals, import regression, window states, guard) — suite green
- Live verified on the target machine: window at ~12s with Loading state, Ready transition, no tracebacks
- Merge gate: user's real dictation after model ready

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
gh pr checks --watch
```
Expected: `tests` and `lint` green (rounds ~1-4 min). If a check fails: `gh run view --log-failed`, fix minimally on the branch, commit with the trailer, push, re-watch. A plausible failure: the offscreen `QT_QPA_PLATFORM` tests on the runner — if the offscreen platform cannot initialize there, the module-level skip in `tests/test_main_window_states.py` handles it (that is designed degradation, not a failure to fix).

- [ ] **Step 5: STOP — user merge gate**

Do NOT merge. Report DONE with the PR URL. The controller hands the live-dictation gate to the user (launch app, dictate once, confirm identical behavior); the merge and the release PR to `main` happen only after the user confirms.
