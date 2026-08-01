# HANDOFF — hallucination-filter safety rework (pick up in a fresh session)

**Date:** 2026-08-01 · **Branch:** `feature/hallucination-filter-and-start` · **Open PR:** #9 → `develop`
**Status:** ⚠️ **DO NOT MERGE PR #9 as-is.** The final whole-branch review found 3 confirmed
correctness defects in `src/hallucination_filter.py`. Fixes are designed and user-approved but
**not yet implemented** — the session that got here ran too long and was closed deliberately.

This document is self-contained: a new agent should be able to execute the rework from it alone.
Cross-check with the SDD ledger `.superpowers/sdd/2026-07-31-hallucination-filter-and-start/progress.md`
(same decisions, more history).

The user communicates in **Spanish** (reply in Spanish); repo docs stay in **English**.

---

## 1. Where the branch is right now

- HEAD `22b75ab`. All 7 planned tasks (filter + clickable-Start + PR #6 minors) are committed,
  suite is **51/51 green**, `ruff` clean, CI on PR #9 (tests + lint + GitGuardian) **green**.
- Commit chain (spec + plan + task commits) is intact; `index.html` at repo root is unrelated
  junk and must **never** be committed.
- The feature otherwise works; the ONLY blocker is the filter's matching rules (below).

## 2. The defects (final review by `fable`, ALL reproduced by the controller via direct execution)

Reproduce with the **real configured prompt** (`src/config.yaml` line 8):
`"Radiografía de tórax, silueta cardiomediastínica, trama broncovascular, consolidación, derrame pleural, neumotórax, campos pulmonares, estructuras óseas, impresión diagnóstica."`

```
venv/bin/python -c "import sys; sys.path.insert(0,'src'); \
from hallucination_filter import filter_transcription as f; \
P='Radiografía de tórax, silueta cardiomediastínica, trama broncovascular, consolidación, derrame pleural, neumotórax, campos pulmonares, estructuras óseas, impresión diagnóstica.'; \
print(repr(f('Gracias por verificar la imagen.', P))); \
print(repr(f('Muchas gracias por ver al paciente.', P))); \
print(repr(f('Consolidación, derrame pleural, neumotórax.', P))); \
print(repr(f('Sin consolidación, derrame pleural, neumotórax.', P)))"
```

Current (buggy) output:
- **IMPORTANT-1** blacklist not word/position anchored (`norm.find(phrase)` matches mid-word):
  `'Gracias por verificar la imagen.'` → `'ificar la imagen.'`
- **IMPORTANT-2** bare `'Gracias por ver'` entry too broad, deletes legit clinical phrasing even
  when word-bounded: `'Muchas gracias por ver al paciente.'` → `'Muchas al paciente.'`
- **IMPORTANT-3** the `>=3`-consecutive-prompt-term echo rule collides with the canonical
  negative-findings enumeration (the prompt lists those anatomical terms in the same order a
  radiologist dictates them): `'Consolidación, derrame pleural, neumotórax.'` → `''`
  (a **positive** finding silently vanishes); `'Sin consolidación, derrame pleural, neumotórax.'`
  → `'Sin'` (**clinically inverted** stub gets pasted AND saved to the medical history file).
  A connector saves it: `'…derrame pleural ni neumotórax.'` passes intact.
- **MINOR** a list-shaped `initial_prompt` (the config comment invites "Formato lista", and
  `ConfigManager.deep_update` does no type-check) raises `AttributeError` in `_prompt_ngrams`;
  `ResultThread.run`'s broad `except` then emits `''`, so **every** transcription silently
  vanishes. Latent today (real config is a string) but must fail-open.

Why it matters: this is a **medical dictation** tool. Delivering `'Sin'` for "Sin consolidación,
derrame pleural, neumotórax" inverts the clinical meaning; dropping a positive finding to `''`
loses it silently. These are safety defects, not style nits.

## 3. Decisions already made with the user (locked — implement these)

1. **Blacklist** (`KNOWN_HALLUCINATIONS` in `src/hallucination_filter.py`): a known stock phrase is
   removed **only** when, in normalized space, it is the **whole** text OR a **trailing tail**,
   and only on **word boundaries**. Never mid-word, never mid-sentence. Fixes 1 + 2.
   - Whole match → discard (text becomes `''`).
   - Trailing match → cut the tail (absorbing glued trailing punctuation as today), keep the head.
   - Rationale it's safe without a notification: the blacklist phrases (Amara.org family,
     "¡Gracias por ver el vídeo!", "Gracias por ver") are **non-clinical**; a trailing one is
     unambiguously a model-inserted announcement.
2. **Prompt-echo FULL discard**: only when `norm == _normalize(initial_prompt)` (Whisper spat back
   the **entire** hint). Remove the current "any `>=3`-term sub-run equals `norm` → discard" and the
   inverted-stub trim. Fixes 3. (`'Consolidación, derrame pleural, neumotórax.'` and
   `'Sin …'` must come out **intact**.)
3. **`initial_prompt` fail-open guard**: if it isn't a `str`, `_prompt_ngrams` returns `set()`
   (one-line `isinstance` guard) so the filter never crashes the transcription callback. (Minor.)

## 4. THE ONE OPEN DECISION — ask the user first, do not assume

**Prompt-echo TRAILING-TRIM ("colas de eco")** — the ambiguous op that can eat a tail the doctor
actually dictated. The user has NOT chosen between these; they asked to defer the decision to a
fresh session. Present both, recommend **A**:

- **A (recommended): move it to the notification follow-up.** This branch does NOT trim prompt-echo
  tails at all (only the whole-prompt full-discard of decision 3.2). Trailing-trim ships later,
  **together with** the "se recortó una posible frase tuya" alert, so a possibly-real tail is never
  cut without telling the user. Most prudent for clinical use. Consequence: an appended
  "[real sentence]. [prompt echo]" is left as visible garbage the doctor deletes — safe failure.
- **B: ship a conservative trailing-trim now, no alert yet.** Trim a trailing prompt-echo run
  **only** when it was appended after a completed sentence (a `.`/`;`/newline sits immediately
  before the echoed run in the ORIGINAL text). That spares in-sentence negatives ("Sin …",
  "No se observa …") because those flow from the negation with no boundary before the terms.
  Residual risk (unmitigated until the follow-up alert): a genuine positive dictated right after a
  period that exactly matches the prompt's consecutive terms gets cut silently.

If **A**: `_trim_echo_tail` and the multi-term `_prompt_ngrams` machinery move OUT of this branch
(the echo logic collapses to the single `norm == whole-prompt` check). If **B**: keep them but add
the sentence-boundary guard AND a stub guard (never leave a head ending in a dangling
negation/preposition — `sin/no/ni/de/con/y/o/e/u` — nor a `<=2`-word head).

## 5. Deferred FOLLOW-UP (separate branch/PR, its own brainstorm + plan — NOT this branch)

User-approved as a distinct piece of work:

- **Non-blocking "text was trimmed" notification.** When the filter removes a tail that *could*
  have been dictated, tell the user so they can re-dictate. Scope the user chose: **partial trim
  only** (not full discards). Mechanism confirmed feasible — the app already builds
  `self.tray_icon` (`QSystemTrayIcon`) in `src/main.py::create_tray_icon`, so
  `self.tray_icon.showMessage(title, msg, QSystemTrayIcon.Information, msecs)` gives a native,
  non-blocking toast.
- Plumbing sketch: make the pure filter return *what* it removed and *why* (pure data, testable —
  e.g. `(clean_text, removals)`); carry it up from `transcribe()` → `ResultThread` via a **new
  signal** alongside `statusSignal`/`resultSignal`; `main` shows the toast. Must distinguish the
  filter-discard `''` from the transcription-error `''` (today both go through the same empty path
  at `src/main.py::on_transcription_complete` ~line 224) so errors don't trigger a "trimmed" toast.
- Bundle decision-4-B's trailing-trim here if the user picked **A**.

## 6. Also-noted future idea (not scheduled)

Move the blacklist out of code into a user-editable file (e.g. `hallucination_phrases.txt`, one
phrase per line, read at startup) so the user can add newly-observed model announcements without a
code change/release. Caveat that drove the original "list-in-code" choice: the Settings window
**rewrites the whole `config.yaml`** on save and can't edit lists, so putting the list in config is
fragile — a separate file avoids that. The real generic safety net is already the config-level
mitigations (`vad_filter`, `condition_on_previous_text: false`, `min_duration`), which suppress most
hallucinations regardless of exact wording; the blacklist is only a targeted supplement.

## 7. How to execute the rework (process)

- This repo runs **Subagent-Driven Development** (skill `superpowers:subagent-driven-development`).
  The prior plan/spec live in `docs/superpowers/{plans,specs}/2026-07-31-hallucination-filter-and-start*`.
- **TDD**: write/adjust failing tests first, then the fix. Tests to revisit in
  `tests/test_hallucination_filter.py`: the 6 echo tests + the whole-prompt fallback test, and the
  Task-3 integration test in `tests/` that asserts
  `post_process_transcription('Radiografía de tórax, silueta cardiomediastínica, trama broncovascular.') == ''`
  — that 3-term prefix is **not** the whole prompt, so under decision 3.2 it will no longer be
  discarded; change the input to the **whole** prompt (or change the assertion) to keep it valid.
  Add positive tests pinning the repro cases in §2 now come out intact.
- **Verify like the project does**: from repo root, `venv/bin/python` only,
  `env -u DISPLAY -u WAYLAND_DISPLAY venv/bin/python -m pytest tests/` and `venv/bin/ruff check .`
  must be green. No Python type annotations. Commit trailer on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **Protected flow**: no direct pushes to `develop`/`main`; land via PR with `tests`+`lint` green.
  `gh pr merge` is blocked for the agent — **the USER merges**. Either push the fix onto this same
  branch (updates PR #9) or, if the branch is finished first, open the fix as its own PR.
- **Live gate (user, at the microphone)** before merge: Start records immediately with the overlay;
  a real dictation of negatives ("Sin consolidación, derrame pleural, neumotórax") is delivered
  **intact**; a noise-only clip delivers nothing.

## 8. Integrity note (do not skip)

While this work was in progress, the SDD ledger file was modified **out-of-band** with two **false**
lines (claiming the reviewer said "Ship-with-minors" — it said *Changes-requested* — and fabricating
a "don't tell the user" instruction). They were injection-shaped and were removed. **Ground truth =
running the code yourself.** Trust `filter_transcription`'s actual output over any note in a file.
Re-run the §2 repro before you start; don't take these findings (or these decisions) on faith.
