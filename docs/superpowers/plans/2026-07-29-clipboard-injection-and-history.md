# Clipboard Injection & Transcription History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver transcriptions instantly via clipboard paste (instead of character-by-character typing), never lose a dictation to a power cut (local history file), and add a manual "Copy Last" button.

**Architecture:** A new `clipboard` input method in `InputSimulator` (copy → Ctrl+V → restore previous clipboard, with typing fallback); a tiny standalone `transcription_history` module called from `on_transcription_complete` before text delivery; a third button on `MainWindow` wired to a new signal.

**Tech Stack:** PyQt5 (QClipboard), pynput (Ctrl+V simulation), pytest (dev-only, venv).

## Global Constraints

- Always use `venv/bin/python` / `venv/bin/pip`; never the system Python.
- Do NOT upgrade `setuptools` (must stay `<81`) and do NOT edit `requirements.txt` (UTF-16 file; pytest is dev-only, not a runtime dep).
- Run everything from the project root (the app uses cwd-relative paths).
- Repo documentation and code comments are written in English; user-facing strings in the UI stay English (matching the existing UI).
- The GUI app needs X11; unit tests must NOT require a display (mock Qt/pynput).

---

### Task 1: Transcription history module

**Files:**
- Create: `src/transcription_history.py`
- Create: `tests/test_transcription_history.py`
- Modify: `src/main.py` (`on_transcription_complete`, line ~165)

**Interfaces:**
- Produces: `append_transcription(text: str, history_path: str = 'transcription_history.txt') -> str | None` — appends a timestamped line, returns the path written, or `None` when text is empty/whitespace.

- [ ] **Step 1: Install pytest (dev-only) and create the tests folder**

```bash
venv/bin/pip install pytest
mkdir -p tests
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_transcription_history.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from transcription_history import append_transcription


def test_appends_timestamped_line(tmp_path):
    path = tmp_path / 'hist.txt'
    result = append_transcription('informe de tórax sin hallazgos', str(path))
    assert result == str(path)
    content = path.read_text(encoding='utf-8')
    assert 'informe de tórax sin hallazgos' in content
    # Line starts with "[YYYY-MM-DD HH:MM:SS]"
    assert content.startswith('[20')
    assert '] ' in content


def test_appends_multiple_entries(tmp_path):
    path = tmp_path / 'hist.txt'
    append_transcription('primera', str(path))
    append_transcription('segunda', str(path))
    lines = path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 2
    assert 'primera' in lines[0]
    assert 'segunda' in lines[1]


def test_empty_text_writes_nothing(tmp_path):
    path = tmp_path / 'hist.txt'
    assert append_transcription('', str(path)) is None
    assert append_transcription('   ', str(path)) is None
    assert not path.exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_transcription_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'transcription_history'`

- [ ] **Step 4: Write the implementation**

Create `src/transcription_history.py`:

```python
"""Append-only local history of transcriptions.

Protects dictated reports from being lost to power cuts or crashes: every
transcription is appended to a plain text file before it is delivered to
the active window.
"""
from datetime import datetime


def append_transcription(text, history_path='transcription_history.txt'):
    """Append a timestamped transcription to the history file.

    Returns the path written to, or None when text is empty/whitespace.
    """
    if not text or not text.strip():
        return None
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(history_path, 'a', encoding='utf-8') as f:
        f.write(f'[{timestamp}] {text.strip()}\n')
    return history_path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/test_transcription_history.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Wire into the app**

In `src/main.py`, add the import next to the other `from x import y` lines:

```python
from transcription_history import append_transcription
```

Replace the beginning of `on_transcription_complete` (currently `self.input_simulator.typewrite(result)`):

```python
    def on_transcription_complete(self, result):
        """
        When the transcription is complete, save it to the history, type the
        result, and start listening for the activation key again.
        """
        try:
            append_transcription(result)
        except OSError as e:
            print(f'Could not save transcription history: {e}')

        self.input_simulator.typewrite(result)
```

(History failure must never block text delivery — hence the try/except.)

- [ ] **Step 7: Sanity check the app still imports**

Run: `venv/bin/python -c "import sys; sys.path.insert(0, 'src'); import transcription_history; print('ok')"`
Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add tests/test_transcription_history.py src/transcription_history.py src/main.py
git commit -m "feat: save every transcription to a local history file"
```

---

### Task 2: Clipboard injection input method

**Files:**
- Modify: `src/input_simulation.py`
- Modify: `src/config_schema.yaml` (post_processing.input_method, line ~145)
- Modify: `src/config.yaml` (set `input_method: clipboard`)
- Create: `tests/test_input_simulation.py`

**Interfaces:**
- Consumes: `ConfigManager.get_config_value('post_processing', 'input_method')` (existing).
- Produces: `InputSimulator.typewrite(text)` now supports the `clipboard` method — copies `text`, simulates Ctrl+V, restores the previous clipboard; falls back to pynput typing on any failure.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_input_simulation.py`:

```python
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class FakeClipboard:
    def __init__(self, initial='previous content'):
        self.history = [initial]

    def text(self):
        return self.history[-1]

    def setText(self, t):
        self.history.append(t)


class FakeKeyboard:
    """Records pynput calls. Supports the pressed() context manager."""
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(('press', key))

    def release(self, key):
        self.events.append(('release', key))

    def pressed(self, key):
        kb = self
        class _Ctx:
            def __enter__(self):
                kb.events.append(('hold', key))
                return self
            def __exit__(self, *a):
                kb.events.append(('unhold', key))
        return _Ctx()


def make_simulator(fake_keyboard):
    """Build an InputSimulator configured for the clipboard method."""
    import input_simulation
    with patch.object(input_simulation.ConfigManager, 'get_config_value',
                      side_effect=lambda section, key: {
                          'input_method': 'clipboard',
                          'writing_key_press_delay': 0,
                      }[key]):
        sim = input_simulation.InputSimulator()
    sim.keyboard = fake_keyboard
    return sim


def test_clipboard_paste_sets_text_and_restores_previous():
    import input_simulation
    fake_clip = FakeClipboard('previous content')
    fake_kb = FakeKeyboard()
    sim = make_simulator(fake_kb)

    with patch.object(input_simulation.ConfigManager, 'get_config_value',
                      return_value='clipboard'), \
         patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
         patch.object(input_simulation, '_process_qt_events'), \
         patch.object(input_simulation.time, 'sleep'):
        sim.typewrite('texto del informe')

    # The transcription was placed on the clipboard, then the previous
    # content was restored afterwards.
    assert 'texto del informe' in fake_clip.history
    assert fake_clip.text() == 'previous content'
    # Ctrl was held while v was pressed.
    from pynput.keyboard import Key
    assert ('hold', Key.ctrl) in fake_kb.events
    assert ('press', 'v') in fake_kb.events


def test_clipboard_failure_falls_back_to_typing():
    import input_simulation
    fake_kb = FakeKeyboard()
    sim = make_simulator(fake_kb)

    def boom():
        raise RuntimeError('no clipboard')

    with patch.object(input_simulation.ConfigManager, 'get_config_value',
                      side_effect=lambda section, key: {
                          'input_method': 'clipboard',
                          'writing_key_press_delay': 0,
                      }[key]), \
         patch.object(input_simulation, '_get_clipboard', side_effect=boom), \
         patch.object(input_simulation.time, 'sleep'):
        sim.typewrite('ab')

    # Fallback typed the text character by character.
    assert ('press', 'a') in fake_kb.events
    assert ('press', 'b') in fake_kb.events
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `venv/bin/python -m pytest tests/test_input_simulation.py -v`
Expected: FAIL (`_get_clipboard` does not exist yet / clipboard method not handled)

- [ ] **Step 3: Implement the clipboard method**

In `src/input_simulation.py`:

1. Change the pynput import to include `Key`:

```python
from pynput.keyboard import Controller as PynputController, Key
```

2. Add module-level Qt helpers after the imports (kept separate so tests can patch them without a display):

```python
def _get_clipboard():
    """Return the Qt clipboard of the running application."""
    from PyQt5.QtWidgets import QApplication
    return QApplication.clipboard()


def _process_qt_events():
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()
```

3. In `__init__`, make the clipboard method also create a pynput controller (it needs it for Ctrl+V and for the typing fallback):

```python
        if self.input_method in ('pynput', 'clipboard'):
            self.keyboard = PynputController()
```

4. In `typewrite`, add the new branch after the `pynput` one:

```python
        elif self.input_method == 'clipboard':
            self._paste_via_clipboard(text, interval)
```

5. Add the method:

```python
    def _paste_via_clipboard(self, text, interval):
        """
        Deliver the text instantly: copy it to the clipboard, simulate
        Ctrl+V, then restore the previous clipboard contents. Falls back
        to typing with pynput if anything fails.

        Args:
            text (str): The text to paste.
            interval (float): Keystroke interval used only by the fallback.
        """
        try:
            clipboard = _get_clipboard()
            previous = clipboard.text()
            clipboard.setText(text)
            _process_qt_events()
            time.sleep(0.05)
            with self.keyboard.pressed(Key.ctrl):
                self.keyboard.press('v')
                self.keyboard.release('v')
            # Give the target application time to read the clipboard
            # before restoring the previous contents.
            time.sleep(0.3)
            clipboard.setText(previous)
            _process_qt_events()
        except Exception as e:
            print(f'Clipboard paste failed ({e}); falling back to typing.')
            self._typewrite_pynput(text, interval)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `venv/bin/python -m pytest tests/ -v`
Expected: all PASSED (including Task 1 tests)

- [ ] **Step 5: Register the option in the schema and enable it**

In `src/config_schema.yaml`, `post_processing.input_method`: update description and options to:

```yaml
  input_method:
    value: pynput
    type: str
    description: "The method to use for delivering the transcribed text. 'clipboard' pastes the whole text at once via Ctrl+V (fastest); the others type it character by character."
    options:
      - pynput
      - clipboard
      - ydotool
      - dotool
```

In `src/config.yaml`, add at the end:

```yaml
post_processing:
  input_method: clipboard
```

- [ ] **Step 6: Commit**

```bash
git add src/input_simulation.py src/config_schema.yaml tests/test_input_simulation.py
# (src/config.yaml is gitignored user-local config — edit it, do NOT git add it)
git commit -m "feat: add clipboard paste input method with typing fallback"
```

---

### Task 3: "Copy Last" button

**Files:**
- Modify: `src/ui/main_window.py`
- Modify: `src/main.py`

**Interfaces:**
- Consumes: `self.last_transcription` (added here to `WhisperWriterApp`), `_get_clipboard()` pattern from Task 2 (main.py uses `QApplication.clipboard()` directly — it already imports QApplication).
- Produces: `MainWindow.copyLast` (pyqtSignal) emitted by the new button.

- [ ] **Step 1: Add the button to MainWindow**

In `src/ui/main_window.py`:

1. Add the signal next to the existing ones:

```python
    copyLast = pyqtSignal()
```

2. Widen the window so three buttons fit — change the `super().__init__` call:

```python
        super().__init__('WhisperWriter', 460, 180)
```

3. In `initMainUI`, add after the `settings_btn` block and include it in the layout before the stretch:

```python
        copy_btn = QPushButton('Copy Last')
        copy_btn.setFont(QFont('Segoe UI', 10))
        copy_btn.setFixedSize(120, 60)
        copy_btn.clicked.connect(self.copyLast.emit)
```

```python
        button_layout.addWidget(copy_btn)
```

(placed right after `button_layout.addWidget(settings_btn)`).

- [ ] **Step 2: Wire it in the app**

In `src/main.py`:

1. In `initialize_components`, right before `self.main_window.show()` area where signals are connected, add:

```python
        self.last_transcription = ''
        self.main_window.copyLast.connect(self.copy_last_transcription)
```

2. In `on_transcription_complete`, after the history try/except, record the result:

```python
        self.last_transcription = result
```

3. Add the slot method:

```python
    def copy_last_transcription(self):
        """
        Copy the most recent transcription to the clipboard.
        """
        QApplication.clipboard().setText(self.last_transcription)
```

- [ ] **Step 3: Sanity check + run all tests**

Run: `venv/bin/python -m pytest tests/ -v` → all PASSED.
Run: `venv/bin/python -c "import ast; ast.parse(open('src/main.py').read()); ast.parse(open('src/ui/main_window.py').read()); print('ok')"` → `ok`

- [ ] **Step 4: Commit**

```bash
git add src/ui/main_window.py src/main.py
git commit -m "feat: add Copy Last button to main window"
```

---

### Task 4: End-to-end verification & docs

**Files:**
- Modify: `README.md` (Configuration + Features)

- [ ] **Step 1: Launch the app and verify visually**

Run `venv/bin/python run.py` in the background (X11 session required). Verify via screenshot (`DISPLAY=:0 gnome-screenshot -f <scratchpad>/check.png`, delete after) that the main window shows the three buttons: Start, Settings, Copy Last.

- [ ] **Step 2: Verify the clipboard flow end-to-end**

Requires the `medium` model download to be complete. Dictate a short phrase (user assists, or run the Phase 2 benchmark harness): confirm the text appears at once in the focused editor, `transcription_history.txt` contains the timestamped entry, and the "Copy Last" button re-copies it.

- [ ] **Step 3: Update README.md**

In the Configuration section, document `input_method: clipboard` as the project default, and add a note about `transcription_history.txt` (every dictation is appended there; power-cut protection).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document clipboard input method and transcription history"
```

---

## Self-Review

- **Spec coverage:** clipboard injection (Task 2), history (Task 1), Copy button (Task 3), all from the approved Phase 3 of Plan.md. ✓
- **Placeholder scan:** all steps carry real code/commands. ✓
- **Type consistency:** `append_transcription` signature matches between Task 1 definition and main.py usage; `copyLast` signal name consistent between main_window.py and main.py; `_get_clipboard`/`_process_qt_events` defined in Task 2 and patched by its tests. ✓
- **Note:** e2e dictation check (Task 4 Step 2) is gated on the model download finishing; everything else is verifiable immediately.
