"""Code-level safety net against Whisper hallucinations.

The config-level mitigations (vad_filter, condition_on_previous_text: false,
list-shaped initial_prompt, min_duration) stop most hallucinations, but two
failure modes can still reach the output: stock phrases Whisper learned from
subtitled video ("Subtítulos por la comunidad de Amara.org") and a verbatim
echo of the initial_prompt. Both would be appended to the (medical) history
file and pasted into the active window.

This is a MEDICAL dictation tool, so the filter is deliberately conservative:
it only removes text it can be sure the model inserted. A stock phrase is cut
only when it is the WHOLE utterance or a TRAILING tail (word-bounded); it is
never matched mid-word or mid-sentence. A prompt echo is discarded only when
the whole prompt is reproduced verbatim — never a partial run, because the
prompt lists the same anatomical terms a radiologist actually dictates (so
"Sin consolidación, derrame pleural, neumotórax" is real speech, not an echo).
Trimming a *partial* trailing prompt echo is intentionally deferred to a
follow-up that ships it together with a user-facing "text was trimmed" notice
(see docs/superpowers/specs/2026-08-01-filter-safety-rework-HANDOFF.md).

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
    """Cut a known stock phrase only when it is the whole utterance or a
    trailing tail (word-bounded in the normalized string).

    Hallucinated announcements appear as the entire output or glued to the end,
    never embedded in the middle of real dictation. Anchoring to whole/trailing
    is what keeps "Muchas gracias por ver al paciente." or "gracias por
    verificar" from being mangled. Longer phrases are tried first so that a
    phrase containing another ("¡Gracias por ver el vídeo!" vs "Gracias por
    ver") is removed whole instead of leaving a fragment behind.
    """
    phrases = sorted((_normalize(p) for p in KNOWN_HALLUCINATIONS),
                     key=len, reverse=True)
    changed = True
    while changed:
        changed = False
        norm, idx_map = _normalize_with_map(text)
        for phrase in phrases:
            if norm == phrase:
                return ''
            if norm.endswith(' ' + phrase):
                start = idx_map[len(norm) - len(phrase)]
                # Absorb any opening punctuation glued before the phrase
                # ("... ¡Gracias por ver el vídeo!").
                while start > 0 and text[start - 1] in '¡¿"\'(':
                    start -= 1
                text = text[:start].rstrip(' \t\n,;')
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
    norm = _normalize(text)
    if not norm:
        return ''
    # Discard only a verbatim echo of the WHOLE prompt. A non-string prompt
    # (a hand-edited YAML list) disables echo detection rather than crashing.
    if isinstance(initial_prompt, str):
        prompt_norm = _normalize(initial_prompt)
        if prompt_norm and norm == prompt_norm:
            return ''
    return text.strip()
