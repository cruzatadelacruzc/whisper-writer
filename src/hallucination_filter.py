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
