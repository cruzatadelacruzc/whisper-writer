# Hallucination Filter + Clickable-Hotkey Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a code-level anti-hallucination filter (known-phrase blacklist + initial_prompt echo detection), make the Start button behave like pressing the dictation hotkey, and close the five minor findings deferred from PR #6's final review.

**Architecture:** A new pure-function module `src/hallucination_filter.py` (no Qt, no I/O, no config access) is called as the first step of `post_process_transcription()` in `src/transcription.py` — the single choke point through which every transcription (local and API mode) passes before history and delivery. A fully-filtered transcription becomes `''`, which the existing empty-result path in `main.py` already treats as "discard and re-arm". The Start button rework and the PR #6 minors are small, isolated edits to `src/main.py`, `src/ui/main_window.py`, the tests, and `README.md`.

**Tech Stack:** Python 3.10, PyQt5, pytest (headless), `unicodedata` from the stdlib. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-31-hallucination-filter-and-start-design.md` (approved).

## Global Constraints

- Work on branch `feature/hallucination-filter-and-start` (already exists, forked from `develop`; the spec commit is on it). PR goes to `develop`; the USER merges — never run `gh pr merge`.
- Always use `venv/bin/python` from the project root (`/mnt/D4B873F1B873D10A/Dev/Python/whisper-writer`), never the system Python.
- Test suite (headless): `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`. Lint: `venv/bin/ruff check .`. Both must be green before the PR.
- NEVER commit `src/config.yaml` (gitignored user config) or `index.html` (unrelated file at repo root). NEVER edit or convert `requirements.txt` (UTF-16 LE). Do not touch `setuptools`.
- Every commit message ends with the trailer line: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- New code carries no type annotations (matches existing codebase style). Comments/docstrings in English.
- Match existing test-file idioms: `sys.path.insert(0, .../src)` header, module docstring stating why, stubs from `tests/test_main_guards.py` where needed.

---

### Task 1: Filter module — normalization + known-phrase blacklist

**Files:**
- Create: `src/hallucination_filter.py`
- Test: `tests/test_hallucination_filter.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces (used by Tasks 2 and 3):
  - `filter_transcription(text, initial_prompt)` → `str` — returns the cleaned text, or `''` if nothing legitimate remains. In this task `initial_prompt` is accepted but unused (echo steps arrive in Task 2).
  - `KNOWN_HALLUCINATIONS` — list of known stock phrases (module constant).
  - `_normalize(text)` → `str` and `_normalize_with_map(text)` → `(str, list[int])` — internal helpers Task 2 reuses.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hallucination_filter.py`:

```python
"""Anti-hallucination filter: known stock phrases and initial_prompt echoes
must never reach delivery or the medical history file (spec:
2026-07-31-hallucination-filter-and-start-design). Pure string tests."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hallucination_filter import filter_transcription  # noqa: E402

# The user's real list-shaped prompt (9 comma-separated radiology terms).
PROMPT = ('Radiografía de tórax, silueta cardiomediastínica, trama '
          'broncovascular, consolidación, derrame pleural, neumotórax, '
          'campos pulmonares, estructuras óseas, impresión diagnóstica.')


def test_amara_exact_is_discarded():
    assert filter_transcription(
        'Subtítulos por la comunidad de Amara.org', PROMPT) == ''


def test_amara_variants_are_discarded():
    # Casing, accents and punctuation must not matter.
    assert filter_transcription(
        ' subtitulos por la comunidad de amara org ', PROMPT) == ''
    assert filter_transcription(
        'Subtitulado por la comunidad de Amara.org.', PROMPT) == ''
    assert filter_transcription(
        'Subtítulos realizados por la comunidad de Amara.org', PROMPT) == ''


def test_gracias_por_ver_is_discarded():
    assert filter_transcription('¡Gracias por ver el vídeo!', PROMPT) == ''
    assert filter_transcription('Gracias por ver.', PROMPT) == ''


def test_two_hallucinations_together_are_discarded():
    assert filter_transcription(
        'Subtítulos por la comunidad de Amara.org ¡Gracias por ver el vídeo!',
        PROMPT) == ''


def test_hallucination_after_real_text_is_stripped():
    assert filter_transcription(
        'Consolidación en lóbulo superior derecho. '
        'Subtítulos por la comunidad de Amara.org',
        PROMPT) == 'Consolidación en lóbulo superior derecho.'


def test_longest_phrase_wins_no_leftover_fragment():
    # "Gracias por ver" is a prefix of "¡Gracias por ver el vídeo!": the
    # longer phrase must be removed as a whole, not leave "el vídeo" behind.
    assert filter_transcription(
        'Informe listo. ¡Gracias por ver el vídeo!', PROMPT) == 'Informe listo.'


def test_real_dictation_is_untouched():
    text = 'Se observa consolidación basal derecha sin derrame pleural.'
    assert filter_transcription(text, PROMPT) == text


def test_empty_and_whitespace_input():
    assert filter_transcription('', PROMPT) == ''
    assert filter_transcription('   \n ', PROMPT) == ''
    assert filter_transcription(None, PROMPT) == ''
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py -v`
Expected: collection ERROR — `ModuleNotFoundError: No module named 'hallucination_filter'`.

- [ ] **Step 3: Write the implementation**

Create `src/hallucination_filter.py`:

```python
"""Code-level safety net against Whisper hallucinations.

The config-level mitigations (vad_filter, condition_on_previous_text: false,
list-shaped initial_prompt, min_duration) stop most hallucinations, but two
failure modes can still reach the output: stock phrases Whisper learned from
subtitled video ("Subtítulos por la comunidad de Amara.org") and verbatim
echoes of the initial_prompt. Both would be appended to the (medical) history
file and pasted into the active window.

Pure string processing — no Qt, no I/O, no config access: the caller passes
the initial_prompt in (spec: 2026-07-31-hallucination-filter-and-start).
"""
import unicodedata

# Known stock phrases, matched in normalized form (case/accent/punctuation
# insensitive). Extend this list as new ones are observed live.
KNOWN_HALLUCINATIONS = [
    'Subtítulos por la comunidad de Amara.org',
    'Subtitulado por la comunidad de Amara.org',
    'Subtítulos realizados por la comunidad de Amara.org',
    '¡Gracias por ver el vídeo!',
    'Gracias por ver',
]


def _normalize_with_map(text):
    """Normalize for comparison, keeping a map back to the original string.

    Lowercase, accents stripped (NFD), every punctuation run collapsed to a
    single space, whitespace collapsed. Returns (normalized, index_map) where
    index_map[i] is the index in `text` of the character that produced
    normalized[i].
    """
    out = []
    idx_map = []
    prev_space = True  # swallow leading separators
    for i, ch in enumerate(text):
        decomposed = unicodedata.normalize('NFD', ch)
        base = ''.join(c for c in decomposed if not unicodedata.combining(c))
        if not base or not base.isalnum():
            if not prev_space:
                out.append(' ')
                idx_map.append(i)
                prev_space = True
            continue
        for c in base.lower():
            out.append(c)
            idx_map.append(i)
        prev_space = False
    if out and out[-1] == ' ':
        out.pop()
        idx_map.pop()
    return ''.join(out), idx_map


def _normalize(text):
    return _normalize_with_map(text)[0]


def _strip_blacklist(text):
    """Cut every occurrence of every known phrase out of the original string.

    Longer phrases are matched first so that a phrase containing another
    ("¡Gracias por ver el vídeo!" vs "Gracias por ver") is removed whole
    instead of leaving a fragment behind.
    """
    phrases = sorted((_normalize(p) for p in KNOWN_HALLUCINATIONS),
                     key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        norm, idx_map = _normalize_with_map(text)
        for phrase in phrases:
            pos = norm.find(phrase)
            if pos == -1:
                continue
            start = idx_map[pos]
            end = idx_map[pos + len(phrase) - 1] + 1
            # Take the punctuation glued to the phrase with it ("...org.",
            # "...vídeo!", leading "¡").
            while end < len(text) and not text[end].isalnum() \
                    and not text[end].isspace():
                end += 1
            while start > 0 and text[start - 1] in '¡¿"\'(':
                start -= 1
            left = text[:start].rstrip()
            right = text[end:].lstrip()
            text = (left + ' ' + right) if left and right else (left or right)
            changed = True
            break
    return text


def filter_transcription(text, initial_prompt):
    """Return `text` cleaned of known hallucinations, or '' to discard it.

    An empty return value flows through the existing empty-result path in
    main.py: nothing is saved to history, delivered, or pasted.
    """
    if not text or not text.strip():
        return ''
    text = _strip_blacklist(text)
    if not _normalize(text):
        return ''
    return text.strip()
```

(`initial_prompt` is intentionally unused until Task 2 adds the echo steps.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py -v`
Expected: all 8 tests PASS. If `ruff` would flag the unused `initial_prompt` argument: it does not (ARG rules are not in the selected set), but run `venv/bin/ruff check src/hallucination_filter.py tests/test_hallucination_filter.py` to confirm 0 findings.

- [ ] **Step 5: Commit**

```bash
git add src/hallucination_filter.py tests/test_hallucination_filter.py
git commit -m "feat: add known-phrase hallucination blacklist filter

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Filter module — prompt-echo detection (full echo + trailing echo)

**Files:**
- Modify: `src/hallucination_filter.py` (extend `filter_transcription`, add helpers)
- Test: `tests/test_hallucination_filter.py` (append tests)

**Interfaces:**
- Consumes: `_normalize`, `_normalize_with_map`, `filter_transcription` from Task 1.
- Produces: `MIN_ECHO_TERMS = 3` (module constant), `_prompt_ngrams(initial_prompt)` → `set[str]`, `_trim_echo_tail(text, ngrams)` → `str`. `filter_transcription` now actually uses `initial_prompt`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hallucination_filter.py`:

```python
def test_full_echo_of_three_terms_is_discarded():
    # Terms 1-3 of the prompt, verbatim and consecutive → echo.
    assert filter_transcription(
        'Radiografía de tórax, silueta cardiomediastínica, '
        'trama broncovascular.', PROMPT) == ''


def test_whole_prompt_echo_is_discarded():
    assert filter_transcription(PROMPT, PROMPT) == ''


def test_one_or_two_terms_are_never_discarded():
    # Below the MIN_ECHO_TERMS=3 threshold: legitimate short dictations.
    assert filter_transcription('Derrame pleural.', PROMPT) == 'Derrame pleural.'
    assert filter_transcription(
        'derrame pleural, neumotórax', PROMPT) == 'derrame pleural, neumotórax'


def test_dictation_with_connectors_is_not_an_echo():
    # Contains prompt terms, but with the speaker's own connective words.
    text = ('Se observa consolidación basal derecha sin derrame pleural '
            'ni neumotórax.')
    assert filter_transcription(text, PROMPT) == text


def test_trailing_echo_is_trimmed_real_text_kept():
    # Terms 4-7 of the prompt glued to the end of a real dictation.
    assert filter_transcription(
        'Estudio dentro de límites normales. Consolidación, derrame '
        'pleural, neumotórax, campos pulmonares',
        PROMPT) == 'Estudio dentro de límites normales.'


def test_none_prompt_disables_echo_but_keeps_blacklist():
    assert filter_transcription('¡Gracias por ver el vídeo!', None) == ''
    text = ('Radiografía de tórax, silueta cardiomediastínica, '
            'trama broncovascular.')
    assert filter_transcription(text, None) == text
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py -v`
Expected: the Task 1 tests still PASS; `test_full_echo_of_three_terms_is_discarded`, `test_whole_prompt_echo_is_discarded` and `test_trailing_echo_is_trimmed_real_text_kept` FAIL (echo not implemented). The threshold/None tests may already pass — that is fine.

- [ ] **Step 3: Implement the echo steps**

In `src/hallucination_filter.py`, add below `KNOWN_HALLUCINATIONS`:

```python
# An echo must span at least this many consecutive prompt terms to be
# discarded or trimmed: dictations of one or two real terms must survive.
MIN_ECHO_TERMS = 3
```

Add the two helpers (below `_strip_blacklist`):

```python
def _prompt_ngrams(initial_prompt):
    """Normalized consecutive runs of >= MIN_ECHO_TERMS prompt terms.

    The whole prompt is always included, which also covers prompts shorter
    than the threshold.
    """
    if not initial_prompt:
        return set()
    terms = [_normalize(t) for t in initial_prompt.split(',')]
    terms = [t for t in terms if t]
    ngrams = set()
    for n in range(MIN_ECHO_TERMS, len(terms) + 1):
        for i in range(len(terms) - n + 1):
            ngrams.add(' '.join(terms[i:i + n]))
    whole = _normalize(initial_prompt)
    if whole:
        ngrams.add(whole)
    return ngrams


def _trim_echo_tail(text, ngrams):
    """If the text ends with an echoed prompt run, cut that tail off."""
    norm, idx_map = _normalize_with_map(text)
    best = None
    for g in ngrams:
        if norm.endswith(' ' + g) and (best is None or len(g) > len(best)):
            best = g
    if best is None:
        return text
    tail_start = idx_map[len(norm) - len(best)]
    return text[:tail_start].rstrip(' \t\n,;')
```

Replace the body of `filter_transcription` with:

```python
    if not text or not text.strip():
        return ''
    text = _strip_blacklist(text)
    norm = _normalize(text)
    if not norm:
        return ''
    ngrams = _prompt_ngrams(initial_prompt)
    if ngrams:
        if norm in ngrams:
            return ''
        text = _trim_echo_tail(text, ngrams)
    return text.strip()
```

- [ ] **Step 4: Run the whole filter test file, verify all pass**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py -v`
Expected: all 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hallucination_filter.py tests/test_hallucination_filter.py
git commit -m "feat: discard/trim initial_prompt echoes (>=3-term runs)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Wire the filter into post_process_transcription

**Files:**
- Modify: `src/transcription.py:91-104` (`post_process_transcription`) and its imports
- Test: `tests/test_hallucination_filter.py` (append integration tests)

**Interfaces:**
- Consumes: `filter_transcription(text, initial_prompt)` from Tasks 1-2.
- Produces: `post_process_transcription` now returns `''` for fully-filtered input and never applies trailing-space/period handling to it. Downstream (`main.on_transcription_complete`) already handles `''` — no changes there.

- [ ] **Step 1: Write the failing integration tests**

Append to `tests/test_hallucination_filter.py`:

```python
def test_post_process_returns_empty_for_pure_hallucination():
    """Integration: the filter runs first inside post_process_transcription,
    and a fully-filtered result skips the trailing-space handling."""
    from unittest.mock import patch
    import transcription

    def fake_section(name):
        return {
            'model_options': {'common': {'initial_prompt': PROMPT}},
            'post_processing': {'remove_trailing_period': False,
                                'add_trailing_space': True,
                                'remove_capitalization': False},
        }[name]

    with patch.object(transcription.ConfigManager, 'get_config_section',
                      side_effect=fake_section):
        assert transcription.post_process_transcription(
            'Subtítulos por la comunidad de Amara.org') == ''
        # Real text still gets the normal post-processing (trailing space).
        assert transcription.post_process_transcription(
            'Sin hallazgos agudos.') == 'Sin hallazgos agudos. '
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py::test_post_process_returns_empty_for_pure_hallucination -v`
Expected: FAIL — the Amara phrase comes back (with a trailing space) because `post_process_transcription` does not filter yet.

- [ ] **Step 3: Integrate the filter**

In `src/transcription.py`, add the import after `from utils import ConfigManager`:

```python
from hallucination_filter import filter_transcription
```

Replace `post_process_transcription` (currently lines 91-104) with:

```python
def post_process_transcription(transcription):
    """
    Apply post-processing to the transcription.
    """
    model_options = ConfigManager.get_config_section('model_options')
    transcription = filter_transcription(
        transcription, model_options['common']['initial_prompt'])
    if not transcription:
        return ''
    post_processing = ConfigManager.get_config_section('post_processing')
    if post_processing['remove_trailing_period'] and transcription.endswith('.'):
        transcription = transcription[:-1]
    if post_processing['add_trailing_space']:
        transcription += ' '
    if post_processing['remove_capitalization']:
        transcription = transcription.lower()

    return transcription
```

(The old leading `transcription.strip()` is gone: the filter already strips.)

- [ ] **Step 4: Run the file and the import-regression test**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_hallucination_filter.py tests/test_transcription_imports.py -v`
Expected: all PASS (`hallucination_filter` is stdlib-only, so `import transcription` stays cheap).

- [ ] **Step 5: Commit**

```bash
git add src/transcription.py tests/test_hallucination_filter.py
git commit -m "feat: run the hallucination filter on every transcription

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Start as clickable hotkey + stale guard comment + README

**Files:**
- Modify: `src/main.py:60` (signal connection), `src/main.py:79-90` area (new slot), `src/main.py:174-179` (guard comment)
- Modify: `README.md:142`, `README.md:144`, `README.md:148-151`
- Test: `tests/test_main_guards.py` (append)

**Interfaces:**
- Consumes: existing `on_activation()` and `key_listener.start()` (both already in `main.py`; `key_listener.start()` is safely re-callable — it is invoked after every transcription).
- Produces: slot `on_start_pressed(self)` on `WhisperWriterApp`; `startListening` now connects to it instead of `key_listener.start`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_main_guards.py`:

```python
def test_on_start_pressed_arms_listener_and_runs_activation_path():
    """Start behaves like pressing the hotkey: arm + same toggle path."""
    fake_self = MagicMock()
    main.WhisperWriterApp.on_start_pressed(fake_self)
    fake_self.key_listener.start.assert_called_once_with()
    fake_self.on_activation.assert_called_once_with()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_guards.py -v`
Expected: the new test FAILS with `AttributeError: ... has no attribute 'on_start_pressed'`; the existing tests PASS.

- [ ] **Step 3: Implement the slot and rewire the signal**

In `src/main.py`, change line 60 from:

```python
        self.main_window.startListening.connect(self.key_listener.start)
```

to:

```python
        self.main_window.startListening.connect(self.on_start_pressed)
```

Add the slot right after `on_model_load_failed` (after current line 90):

```python
    def on_start_pressed(self):
        """The Start button behaves like pressing the hotkey: arm the
        listener, then run the same toggle path (start or stop recording).
        The window hides itself on click, so focus returns to the target
        app; the user stops with the hotkey (or by clicking Start again
        after reopening the window from the tray)."""
        self.key_listener.start()
        self.on_activation()
```

Replace the stale guard comment in `start_result_thread` (currently lines 175-177):

```python
        # The hotkey is only armed via Start (disabled until the model is
        # ready), but guard anyway: ResultThread with local_model=None would
        # sync-load the model inside the recording thread.
```

with:

```python
        # Start is disabled until the model is ready, but the hotkey can be
        # armed before that (an explicit input_backend arms it at startup):
        # without this guard a hotkey press would hand local_model=None to
        # ResultThread, which would sync-load the model inside the
        # recording thread.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_guards.py -v`
Expected: all PASS.

- [ ] **Step 5: Update README.md**

Replace line 142:

```markdown
- Dictation hotkey: **`ctrl+shift+space`** (configurable). **Start does not record by itself — it arms the hotkey**; recording begins when you press the hotkey (that is when the status overlay appears).
```

with:

```markdown
- Dictation hotkey: **`ctrl+shift+space`** (configurable). **Clicking Start behaves exactly like pressing the hotkey**: it arms the hotkey and starts recording immediately (the status overlay appears and the window hides). Later recordings are started and stopped with the hotkey.
```

In line 144, replace the fragment `**Start** (arm the dictation hotkey)` with `**Start** (arm the hotkey and start recording — a click behaves like a hotkey press)`.

Replace flow steps 1-3 (lines 148-150):

```markdown
1. Wait for **Model ready**, press **Start** (the window hides; the hotkey is now armed).
2. Place the cursor in the target document and press **`ctrl+shift+space`** — the status overlay shows *recording*.
3. Speak one phrase. Recording stops on its own after ~0.9 s of silence (`recording_options.silence_duration`), the overlay shows *transcribing*, and the text is pasted into the active window.
```

with:

```markdown
1. Wait for **Model ready**, press **Start** — recording begins immediately and the window hides. Focus the target document while you speak: the text lands in the **active** window when transcription finishes.
2. Speak one phrase. How recording stops depends on `recording_options.recording_mode` (table below): with the recommended `press_to_toggle` you press the hotkey when the phrase is done; the VAD-based modes (`continuous`, `voice_activity_detection`) stop on their own after ~0.9 s of silence (`recording_options.silence_duration`).
3. The overlay shows *transcribing* and the text is pasted into the active window. For the next phrase press **`ctrl+shift+space`** — the hotkey stays armed.
```

Keep step 4 ("What happens next depends on...") and the table unchanged. (Step 2's wording also fixes a pre-existing inaccuracy: the old step 3 claimed silence auto-stop for every mode, but `press_to_toggle`/`hold_to_record` have no VAD.)

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_guards.py README.md
git commit -m "feat: make the Start button act like a hotkey press

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: PR #6 minors — initial button state, loader-slot tests, first-run robustness

**Files:**
- Modify: `src/ui/main_window.py:27-30` (initial Start state)
- Modify: `src/main.py:20-38` (`__init__`), `src/main.py:40-77` (`initialize_components`), `src/main.py:134-144` (`on_settings_closed`)
- Test: `tests/test_main_window_states.py`, `tests/test_main_guards.py` (append)

**Interfaces:**
- Consumes: `setModelLoading/setModelReady/setModelError` (existing), `on_model_ready`/`on_model_load_failed` (existing slots in `main.py`).
- Produces: `self.components_initialized` flag on `WhisperWriterApp`; `key_listener`/`input_simulator` guaranteed to exist (as `None`) from `__init__` on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_window_states.py`:

```python
def test_start_button_disabled_at_construction(window):
    """No race window between show() and setModelLoading(): the button is
    born disabled and only the state methods enable it."""
    assert window.start_btn.isEnabled() is False
```

Append to `tests/test_main_guards.py`:

```python
def test_on_model_ready_stores_model_and_unlocks_window():
    fake_self = MagicMock()
    model = object()
    main.WhisperWriterApp.on_model_ready(fake_self, model)
    assert fake_self.local_model is model
    fake_self.main_window.setModelReady.assert_called_once_with()


def test_on_model_load_failed_shows_error_state_and_warning():
    fake_self = MagicMock()
    with patch.object(main.QMessageBox, 'warning') as warning:
        main.WhisperWriterApp.on_model_load_failed(fake_self, 'boom')
    fake_self.main_window.setModelError.assert_called_once_with()
    warning.assert_called_once()
    assert 'boom' in warning.call_args[0][2]


def test_cleanup_tolerates_never_initialized_components():
    """First run: saving Settings triggers restart_app -> cleanup() before
    initialize_components() ever ran. __init__ now pre-sets the attributes
    to None, and cleanup's guards must accept that."""
    fake_self = MagicMock()
    fake_self.key_listener = None
    fake_self.input_simulator = None
    main.WhisperWriterApp.cleanup(fake_self)  # must not raise


def test_on_settings_closed_skips_when_already_initialized():
    """Closing Settings unsaved more than once must not initialize the
    components again (duplicate tray icon / listeners). os.path.exists is
    patched to False so the test exercises the flag, not the real
    config.yaml on this machine."""
    fake_self = MagicMock()
    fake_self.components_initialized = True
    with patch.object(main.os.path, 'exists', return_value=False), \
         patch.object(main.QMessageBox, 'information'):
        main.WhisperWriterApp.on_settings_closed(fake_self)
    fake_self.initialize_components.assert_not_called()


def test_on_settings_closed_initializes_on_first_run():
    fake_self = MagicMock()
    fake_self.components_initialized = False
    with patch.object(main.os.path, 'exists', return_value=False), \
         patch.object(main.QMessageBox, 'information'):
        main.WhisperWriterApp.on_settings_closed(fake_self)
    fake_self.initialize_components.assert_called_once_with()
```

- [ ] **Step 2: Run them to verify the right ones fail**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_window_states.py tests/test_main_guards.py -v`
Expected: `test_start_button_disabled_at_construction` FAILS (the button is currently born enabled) and `test_on_settings_closed_skips_when_already_initialized` FAILS (no flag check yet, and with `os.path.exists` patched to False the current code goes on to call `initialize_components`). The slot tests, `test_cleanup_tolerates_never_initialized_components` and `test_on_settings_closed_initializes_on_first_run` PASS already — they lock existing behavior against regressions, which is part of this task's point.

- [ ] **Step 3: Implement**

`src/ui/main_window.py` — after line 30 (`self.start_btn.clicked.connect(self.startPressed)`), add:

```python
        # Born disabled: only the model-state methods (setModelLoading /
        # setModelReady / setModelError) control this button.
        self.start_btn.setEnabled(False)
```

`src/main.py` — in `__init__`, right after `super().__init__()` (line 24), add:

```python
        # Pre-set so cleanup()/restart_app() are safe even if
        # initialize_components() never ran (first run: Settings only).
        self.key_listener = None
        self.input_simulator = None
        self.components_initialized = False
```

In `initialize_components`, add as the LAST line of the method (after the model-loader block):

```python
        self.components_initialized = True
```

In `on_settings_closed`, add the guard as the first statement:

```python
        if self.components_initialized:
            return
```

- [ ] **Step 4: Run the tests to verify everything passes**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_main_window_states.py tests/test_main_guards.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ui/main_window.py src/main.py tests/test_main_window_states.py tests/test_main_guards.py
git commit -m "fix: close PR #6 review minors (initial state, slots, first run)

Start button is born disabled; on_model_ready/on_model_load_failed are
pinned by tests; cleanup()/on_settings_closed no longer break on a first
run (AttributeError on restart, double component initialization).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Broaden the import-regression test

**Files:**
- Modify: `tests/test_transcription_imports.py` (full rewrite, parametrized)

**Interfaces:**
- Consumes: `src/model_load_thread.py` and `src/result_thread.py` as import targets (plus `transcription`).
- Produces: nothing new — a wider regression net.

- [ ] **Step 1: Rewrite the test file**

Replace the whole content of `tests/test_transcription_imports.py` with:

```python
"""Startup-path imports must stay cheap: faster_whisper/openai are deferred
into the functions that use them (spec: async-model-load). A module-level
reimport in transcription.py OR in anything the GUI imports at startup
(model_load_thread, result_thread) would put ~40s back on the startup path,
so each module is checked in a CLEAN subprocess interpreter, not in-process."""
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


@pytest.mark.parametrize('module', [
    'transcription',
    'model_load_thread',
    'result_thread',
])
def test_importing_module_does_not_pull_heavy_libraries(module):
    check = (
        "import sys, os;"
        "sys.path.insert(0, os.path.join(%r, 'src'));"
        "import %s;"
        "assert 'faster_whisper' not in sys.modules, 'faster_whisper imported at module level';"
        "assert 'openai' not in sys.modules, 'openai imported at module level';"
        "print('DEFERRED_OK')"
    ) % (PROJECT_ROOT, module)
    result = subprocess.run(
        [sys.executable, '-c', check],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert 'DEFERRED_OK' in result.stdout
```

- [ ] **Step 2: Run it to verify all three parametrizations pass**

Run: `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/test_transcription_imports.py -v`
Expected: 3 PASS (`result_thread` imports sounddevice/webrtcvad/PyQt5.QtCore — none of them pulls the heavy pair; webrtcvad's `pkg_resources is deprecated` warning on stderr is harmless, the assertion is on the return code).

- [ ] **Step 3: Commit**

```bash
git add tests/test_transcription_imports.py
git commit -m "test: extend import-regression net to model_load_thread and result_thread

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Full verification and PR

**Files:**
- None created; runs checks and opens the PR.

- [ ] **Step 1: Run the complete suite and the linter**

```bash
env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/
venv/bin/ruff check .
```

Expected: all tests PASS (26 pre-existing + the new ones), ruff 0 findings. Fix anything that fails before continuing.

- [ ] **Step 2: Sanity-check the branch contents**

```bash
git log --oneline develop..HEAD
git status --short
```

Expected: the spec commit + the 6 task commits; working tree clean except the untracked `index.html` (which must NEVER be added).

- [ ] **Step 3: Push and open the PR (do NOT merge)**

```bash
git push -u origin feature/hallucination-filter-and-start
gh pr create --base develop --title "feat: hallucination filter, clickable-hotkey Start, PR #6 minors" --body "$(cat <<'EOF'
## Summary
- New `src/hallucination_filter.py`: known-phrase blacklist (Amara.org & friends, normalized matching) + initial_prompt echo detection (full-echo discard and trailing-echo trim, >=3 consecutive prompt terms), wired in as the first step of `post_process_transcription()` — covers local & API mode, history and delivery. A fully-filtered result rides the existing empty-result path (discard + re-arm).
- The Start button now behaves like pressing the dictation hotkey: it arms the listener and starts recording immediately (window hides, as before). README updated accordingly.
- Closes the five minors deferred from PR #6's final review: broadened import-regression test (model_load_thread, result_thread), stale guard comment fixed, loader-slot tests, Start button born disabled, first-run robustness (cleanup AttributeError, double initialize_components).

## Test plan
- [x] `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/` — all green (headless)
- [x] `venv/bin/ruff check .` — clean
- [ ] Live gate (user at the microphone): Start begins recording immediately with the overlay visible and delivers a real dictation; a noise/silence-only recording delivers nothing (no Amara phrase, no prompt echo)

Spec: `docs/superpowers/specs/2026-07-31-hallucination-filter-and-start-design.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI until both checks are green**

```bash
gh pr checks --watch
```

Expected: `tests` and `lint` SUCCESS. If a check fails, read the log (`gh run view --log-failed`), fix, commit, push, and re-watch.

- [ ] **Step 5: Hand over to the user**

Report (in Spanish): PR URL, checks green, and that the live gate is theirs — launch `venv/bin/python run.py` from the project root, click Start (recording must begin at once), dictate one real phrase, and try a noise-only recording. The USER merges the PR (`gh pr merge` is blocked for the agent).
