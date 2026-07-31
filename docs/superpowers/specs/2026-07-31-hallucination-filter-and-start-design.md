# Hallucination Filter + Clickable-Hotkey Start — Design

**Date:** 2026-07-31
**Status:** Approved by user (brainstorming session)
**Scope:** One feature branch / PR to `develop` containing three things:
(1) an in-code anti-hallucination filter (known-phrase blacklist + prompt-echo
detection), (2) the Start button reworked to behave like pressing the global
hotkey, (3) the five minor findings deferred from PR #6's final review.
The Word/Writer export from `Plan.md` is explicitly out of scope (its own
future project).

## Background

The config-level mitigations (`vad_filter`, `condition_on_previous_text:
false`, list-shaped `initial_prompt`, `min_duration: 1400`) eliminated the
observed hallucination storms, but two failure modes can still reach the
output: Whisper emitting a known stock phrase ("Subtítulos por la comunidad
de Amara.org", "¡Gracias por ver el vídeo!") on a noisy-but-long-enough clip,
and Whisper echoing a chunk of the `initial_prompt` verbatim. Both would be
saved to the (medical) history file and pasted into the active window. This
design adds a code-level safety net.

Separately, live use showed the Start button's arm-only behavior confuses
(no recording banner appears); the user chose to make Start act exactly like
a hotkey press.

## Decisions made during brainstorming

| Question | Decision |
|----------|----------|
| Batch scope | Filter + Start rework + the 5 PR #6 minors in one PR; Word/Writer export excluded. |
| Start behavior | Clickable hotkey: click arms the listener AND triggers the same toggle path as the hotkey (`on_activation`). Window keeps hiding on click. |
| Echo-filter aggressiveness | Full-echo discard **plus** trailing-echo trim, both with a ≥ 3 consecutive prompt terms threshold. |
| Filter architecture | Approach A: new pure module `src/hallucination_filter.py` called from `post_process_transcription()`; blacklist is a curated module constant (the config schema has no list type and the Settings window rewrites `config.yaml` on save — not worth the new surface). |

## Components

### 1. `src/hallucination_filter.py` (new, pure functions, no Qt)

- `_normalize(text)` — lowercase, strip accents (NFD, drop combining marks),
  punctuation → space, collapse whitespace. All comparisons use this form;
  delivered text keeps its original casing/accents/punctuation.
- `KNOWN_HALLUCINATIONS` — module constant with the known stock phrases
  (compared normalized): "Subtítulos por la comunidad de Amara.org",
  "Subtitulado por la comunidad de Amara.org", "Subtítulos realizados por la
  comunidad de Amara.org", "¡Gracias por ver el vídeo!", "Gracias por ver".
  Extending it is a one-line code edit.
- `filter_transcription(text, initial_prompt) -> str` applies, in order:
  1. **Blacklist strip:** remove every occurrence of each known phrase
     wherever it appears (including appended after real dictation), matching
     in normalized space but cutting from the original string. Empty
     result → `''`.
  2. **Full-echo discard:** split the prompt into terms (on commas; a
     trailing period is tolerated), build every consecutive run of ≥ 3
     terms; if the normalized transcription equals one of those runs (or the
     whole prompt) → `''`. The ≥ 3 threshold protects real dictations: one
     or two prompt terms alone ("derrame pleural") are never discarded.
  3. **Trailing-echo trim:** if the normalized transcription *ends with* a
     ≥ 3-term consecutive run, cut that tail from the original string and
     keep the rest.
- `initial_prompt` may be `None`/empty (echo steps become no-ops; blacklist
  still applies).

### 2. `src/transcription.py` (integration)

`post_process_transcription()` calls `filter_transcription(text,
model_options['common']['initial_prompt'])` as its **first** step; if the
filter returns `''`, return `''` immediately (skip trailing-period/space/
capitalization handling). This single choke point covers local **and** API
mode, the history file, and delivery; `result_thread`'s console log already
prints the post-processed (now filtered) line.

`''` needs no new plumbing downstream: `on_transcription_complete` already
treats an empty result as "discard and re-arm the hotkey" (no clipboard
clobber, no stray Ctrl+V, nothing appended to history).

### 3. `src/main.py` (Start as clickable hotkey)

Replace `startListening.connect(self.key_listener.start)` with a new slot
`on_start_pressed()` that calls `self.key_listener.start()` then
`self.on_activation()`. Semantics: clicking Start = pressing the hotkey —
recording starts immediately (banner visible); the window keeps hiding on
click (existing `startPressed` behavior), so focus returns to the target app
and the user stops with the hotkey. If the window is reopened from the tray
mid-recording, clicking Start again toggles stop, exactly like the hotkey.
Start stays disabled until "Model ready", so it can never fire without a
model. `key_listener.start()` is already called repeatedly elsewhere
(after every transcription), so re-arming is safe.

### 4. The five PR #6 review minors

1. **Broaden the import-regression test:** `tests/test_transcription_imports.py`
   must also verify, in a clean subprocess, that importing `model_load_thread`
   and `result_thread` does not pull `faster_whisper`/`openai` into
   `sys.modules` (any of the three could reintroduce the ~40 s stall).
2. **Fix the stale guard comment** in `start_result_thread()` (src/main.py):
   "the hotkey is only armed via Start" is wrong — an explicit
   `input_backend` arms the hotkey at startup, and Start now records
   directly. Rewrite to match reality.
3. **Slot tests** for `on_model_ready` (stores the model, calls
   `setModelReady`) and `on_model_load_failed` (calls `setModelError`, shows
   the warning box — monkeypatched), using the `test_main_guards` stub
   pattern.
4. **`start_btn` starts disabled** in `initMainUI()` — today it is born
   enabled and only `setModelLoading()` (called after `show()`) disables it;
   remove that race window. The state methods remain the only thing that
   enables it.
5. **First-run robustness (pre-existing defects):** saving Settings on first
   run triggers `restart_app()` → `cleanup()` before
   `initialize_components()` ever ran → `AttributeError`. Initialize
   `self.key_listener = None` and `self.input_simulator = None` in
   `__init__` (cleanup already null-guards). And `on_settings_closed` can
   run `initialize_components()` twice (duplicate tray icon/listeners) if
   Settings is closed unsaved more than once while `config.yaml` is still
   absent — guard with an "already initialized" flag.

### 5. README

Update the Start description ("arm the dictation hotkey") to the new
behavior: clicking Start acts like pressing the hotkey — recording starts
immediately and the window hides; stop with the hotkey.

## Error handling

The filter is pure string processing with no I/O; a `None`/empty prompt
disables only the echo steps. A fully-filtered transcription surfaces as the
existing empty-result path (discard + re-arm), which is already covered by
tests. No new failure modes are introduced in the GUI layer: `on_start_pressed`
reuses `on_activation`, whose guards (thread running, model not ready)
already hold.

## Testing (headless, following existing suite patterns)

- `tests/test_hallucination_filter.py` (pure, no Qt): Amara exact and with
  casing/accent/punctuation variants; "Gracias por ver el vídeo";
  hallucination appended after real text → stripped, real text kept;
  full echo of a ≥ 3-term prompt chunk → `''`; 1–2 term dictation
  ("derrame pleural") → kept; real dictation using prompt terms with its own
  connectors → kept; trailing echo → trimmed; empty/whitespace after
  filtering → `''`; `initial_prompt=None` → blacklist only.
- Integration: `post_process_transcription` returns `''` for a pure
  hallucination and does not append the trailing space.
- `test_main_guards` extended: `on_start_pressed` arms the listener and
  triggers the activation path; the minor-3 slot tests; first-run
  robustness (restart before init → no `AttributeError`; double
  `on_settings_closed` → single initialization).
- `test_main_window_states`: the Start button is disabled at construction
  (minor 4). Import-regression test broadened (minor 1).

## Live verification (merge gate, user at the microphone)

Clicking Start must begin recording immediately (recording banner visible)
and deliver a real dictation; a noise/silence-only recording must deliver
nothing (no Amara phrase, no prompt echo).

## Delivery

Branch `feature/hallucination-filter-and-start` from `develop` → PR to
`develop` with green `tests`/`lint` checks → the user's live dictation gate →
the user merges. Release `develop` → `main` when the user decides.

## Out of scope (YAGNI)

Word/Writer export (own future project), a config-driven blacklist (no list
type in the schema; Settings rewrites `config.yaml` on save), `beam_size`/
speed tuning, any Settings-window changes.
