# Partial Echo-Trim + Tray Notification — Design

**Date:** 2026-09-02
**Status:** Approved by user (brainstorming session)
**Scope:** One feature branch / PR to `develop`. Follow-up to PR #9
(`feature/hallucination-filter-and-start`, merged as `3df2768`), specifically
the deferred item in
`docs/superpowers/specs/2026-08-01-filter-safety-rework-HANDOFF.md` §5:
partial trailing prompt-echo trimming, shipped together with a non-blocking
tray notice so a possibly-real tail is never silently discarded. §6 (moving
the blacklist out of code into a user-editable file) is explicitly out of
scope for this branch.

## Background

PR #9 shipped the hallucination filter's *safe* behavior: a stock-phrase
blacklist anchored to whole-utterance/trailing-tail matches, and prompt-echo
detection that discards only a **verbatim whole-prompt** echo. An earlier,
more aggressive version (commit `822d603`) also trimmed a trailing run of
≥3 consecutive prompt terms — but the final review found this corrupted real
dictation: `"Sin consolidación, derrame pleural, neumotórax."` (an in-sentence
negative finding using the same terms as the `initial_prompt`) was reduced to
the clinically inverted stub `"Sin"`. That trim was reverted in `b446fc5` and
formally deferred (HANDOFF §4, decision **A**) to this follow-up, on the
condition that trimming ships together with a user-facing notice.

## Decisions made during brainstorming

| Question | Decision |
|----------|----------|
| Trim rule | Reuse HANDOFF §4 option B: trim a trailing run of ≥3 consecutive prompt terms **only** when a sentence boundary (`.`/`;`/newline) sits immediately before it in the *original* text. Never trim if the resulting head would end in a dangling negation/preposition (`sin/no/ni/de/con/y/o/e/u`) or have ≤2 words. |
| Toast content | Show the exact trimmed fragment in the message (not a generic notice), so the user knows exactly what to re-dictate. |
| Toast trigger | Only on a **partial** trim. Full discards (whole-blacklist match, whole-prompt echo) and transcription errors never show a toast — unchanged from PR #9's rationale that those cases are unambiguous/non-clinical. |
| Plumbing | New dedicated `ResultThread` signal (`echoTrimSignal`) carrying just the trimmed fragment, kept separate from `resultSignal`. The existing `except` branch never emits it, so a transcription error can never be mistaken for a trim — no need for the HACK the HANDOFF's original sketch flagged (distinguishing filter-discard `''` from error `''`). |

## Components

### 1. `src/hallucination_filter.py`

- Reintroduce `MIN_ECHO_TERMS = 3` and `_prompt_ngrams(initial_prompt)`
  (as in `822d603`, reverted in `b446fc5`): normalized consecutive runs of
  ≥3 comma-split prompt terms, plus the whole prompt. Guarded by
  `isinstance(initial_prompt, str)` — a non-string prompt (hand-edited YAML
  list) yields `set()` and disables trimming, mirroring the existing
  whole-prompt-echo guard.
- New `_trim_echo_tail(text, ngrams) -> (text, trimmed_tail)`:
  1. Find the longest ngram for which the *normalized* text ends with
     `' ' + ngram`.
  2. Only accept the trim if, walking back from the match start in the
     **original** string (skipping whitespace and opening-punctuation glue
     the same way `_strip_blacklist` does), the preceding non-space
     character is `.`, `;`, or a newline. If the match starts at position 0
     (no preceding character at all — the whole text is the echoed run),
     the trim is rejected the same as a missing sentence boundary.
  3. Compute the candidate head (text before the trimmed tail, punctuation
     trimmed). Reject the trim (return the text unchanged, `trimmed_tail =
     None`) if the head's word count is ≤2, or if its last word (normalized)
     is in `{sin, no, ni, de, con, y, o, e, u}`.
  4. On acceptance, return `(head, original_tail_substring)` — the tail is
     taken from the *original* text (not the normalized form) so the toast
     shows real casing/accents/punctuation.
- `filter_transcription(text, initial_prompt)` signature changes to
  **`(cleaned_text, trimmed_tail)`**:
  - Empty input → `('', None)`.
  - Blacklist whole-match → `('', None)`. Blacklist trailing-tail cut →
    `(text, None)` (still silent — non-clinical announcements, per PR #9's
    existing rationale).
  - Whole-prompt verbatim echo → `('', None)`.
  - Otherwise, run `_trim_echo_tail`; on a real trim, `trimmed_tail` is the
    cut fragment; the guards above make it impossible for a trim to leave an
    empty or near-empty head.

### 2. `src/transcription.py`

- `post_process_transcription(transcription)` unpacks
  `(transcription, trimmed_tail) = filter_transcription(...)`. Existing
  post-processing (`remove_trailing_period`, `add_trailing_space`,
  `remove_capitalization`) applies only to `transcription`; `trimmed_tail`
  passes through untouched. Returns `(transcription, trimmed_tail)`.
- `transcribe()` returns the same tuple, including the early
  `audio_data is None → ('', None)` path.

### 3. `src/result_thread.py`

- New signal: `echoTrimSignal = pyqtSignal(str)`.
- `run()`: `result, trimmed_tail = transcribe(audio_data, self.local_model)`.
  Emits `resultSignal.emit(result)` exactly as today; additionally emits
  `self.echoTrimSignal.emit(trimmed_tail)` iff `trimmed_tail` is truthy.
- The `except` branch is unchanged (`resultSignal.emit('')` only) — it never
  touches `echoTrimSignal`.

### 4. `src/main.py`

- `start_result_thread()` adds
  `self.result_thread.echoTrimSignal.connect(self.on_echo_trimmed)`.
- New method:
  ```python
  def on_echo_trimmed(self, trimmed_tail):
      self.tray_icon.showMessage(
          'WhisperWriter',
          f'Se recortó posible texto real al final del dictado: '
          f'"{trimmed_tail}". Vuelve a dictarlo si hacía falta.',
          QSystemTrayIcon.Information,
          10000,
      )
  ```
- `on_transcription_complete` is unchanged — delivery (history + typewrite)
  and the trim toast are independent side effects of the same recording
  cycle, not sequenced through each other.

## Data flow

Mic → `ResultThread._record_audio` → `transcribe_local`/`transcribe_api`
(raw text) → `filter_transcription` (blacklist → whole-prompt discard →
guarded echo-tail trim) → `(clean_text, trimmed_tail)` → post-processing on
`clean_text` → `ResultThread` unpacks and emits `resultSignal(clean_text)`
always, plus `echoTrimSignal(trimmed_tail)` only when a trim happened →
`main.py` delivers `clean_text` via the existing path and, independently,
shows the toast when notified.

## Error handling & edge cases

- Exceptions during transcription: caught in `ResultThread.run()`'s
  `except`, which emits only `resultSignal.emit('')`. `echoTrimSignal` is
  never touched, so an error can never trigger the toast.
- Non-`str` `initial_prompt`: `_prompt_ngrams` returns `set()` (fails open),
  same guard style as the existing whole-prompt-echo check.
- A trim can never empty `clean_text`: the ≤2-word-head guard and the
  dangling-negation guard both reject trims that would leave nothing (or
  next-to-nothing) behind.
- `recording_mode: continuous` behavior (auto-restart) is untouched — the
  toast is a side effect, not part of the re-arm/rearm control flow.

## Testing

- `tests/test_hallucination_filter.py` (new cases):
  - A trim fires: text with a real sentence ending in `.` followed by a
    ≥3-term echoed tail → tail removed, head intact, `trimmed_tail` is the
    removed fragment.
  - Regression guard: `"Sin consolidación, derrame pleural, neumotórax."`
    (no sentence boundary before the echoed run — it *is* the sentence) →
    text unchanged, `trimmed_tail is None`.
  - Head-guard cases: a trim that would leave ≤2 words, or a head ending in
    a dangling negation/preposition → not trimmed.
  - Whole-prompt discard and blacklist cases still return
    `trimmed_tail is None`.
  - Non-`str` `initial_prompt` does not crash `_prompt_ngrams` or
    `filter_transcription`.
- `tests/test_main_guards.py`: `ResultThread` exposes `echoTrimSignal`; a
  trimmed result triggers `on_echo_trimmed` → `tray_icon.showMessage` called
  with the fragment; the `except` path never emits `echoTrimSignal`.
- `tests/test_transcription_imports.py`: update call sites for the new tuple
  return from `transcribe()`/`post_process_transcription()` (exact scope of
  the edit is an implementation-time detail, not re-derived here).
- All of the above run headless
  (`env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/`).
- Live gate (user, at the mic, same shape as PR #9's): dictate a real
  sentence followed by a verbatim prompt-term run after a period, confirm
  the toast appears with the correct fragment and the delivered text keeps
  only the real sentence; dictate an in-sentence negative like `"Sin
  consolidación, derrame pleural, neumotórax"` and confirm it is delivered
  intact with no toast.
