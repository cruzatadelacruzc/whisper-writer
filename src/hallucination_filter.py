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
A partial trailing prompt echo IS trimmed, but only when a sentence boundary
(.;/newline) sits right before it in the original text — that is what spares
in-sentence negatives like the example above, since nothing ever precedes
those terms but the word "Sin". The trimmed fragment is reported back to the
caller (never silently dropped) so it can raise a user-facing notice; see
docs/superpowers/specs/2026-09-02-echo-trim-tray-notification-design.md.

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

# An echo must span at least this many consecutive prompt terms to be a
# trim candidate: dictations of one or two real terms must survive.
MIN_ECHO_TERMS = 3

# A trimmed head must not end on a dangling negation/preposition — cutting
# right after one of these would invert or erase the doctor's own sentence.
NEGATION_STUBS = {'sin', 'no', 'ni', 'de', 'con', 'y', 'o', 'e', 'u'}


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


def _prompt_ngrams(initial_prompt):
    """Normalized consecutive runs of >= MIN_ECHO_TERMS prompt terms.

    A non-string prompt (a hand-edited YAML list) disables echo-tail
    detection rather than crashing.
    """
    if not isinstance(initial_prompt, str) or not initial_prompt:
        return set()
    terms = [_normalize(t) for t in initial_prompt.split(',')]
    terms = [t for t in terms if t]
    ngrams = set()
    for n in range(MIN_ECHO_TERMS, len(terms) + 1):
        for i in range(len(terms) - n + 1):
            ngrams.add(' '.join(terms[i:i + n]))
    return ngrams


def _trim_echo_tail(text, ngrams):
    """Cut a trailing run of >= MIN_ECHO_TERMS consecutive prompt terms.

    Only accepted when: (1) a sentence boundary ('.', ';', or a newline)
    sits immediately before the echoed run in the ORIGINAL text — this is
    what spares in-sentence negatives like "Sin consolidación, derrame
    pleural, neumotórax" from being mangled, since nothing but the word
    "Sin" ever precedes those terms there; (2) the remaining head has more
    than 2 words and does not end in a dangling negation/preposition.
    Returns (text, tail): tail is None when nothing was cut.
    """
    if not ngrams:
        return text, None
    norm, idx_map = _normalize_with_map(text)
    best = None
    for g in ngrams:
        if (norm == g or norm.endswith(' ' + g)) and \
                (best is None or len(g) > len(best)):
            best = g
    if best is None:
        return text, None

    start = idx_map[len(norm) - len(best)]
    # Absorb any opening punctuation glued before the tail, same as the
    # blacklist does ("... ¡Radiografía de tórax...").
    while start > 0 and text[start - 1] in '¡¿"\'(':
        start -= 1

    boundary = start - 1
    while boundary >= 0 and text[boundary] in ' \t\n':
        boundary -= 1
    if boundary < 0 or text[boundary] not in '.;\n':
        return text, None

    head = text[:start].rstrip()
    head_words = [w for w in _normalize(head).split(' ') if w]
    if len(head_words) <= 2 or head_words[-1] in NEGATION_STUBS:
        return text, None

    tail = text[start:].strip()
    if any(ch in '.;' for ch in tail[:-1]):
        return text, None

    return head, tail


def filter_transcription(text, initial_prompt):
    """Return (cleaned_text, trimmed_tail).

    cleaned_text is '' to signal the caller should discard the result
    entirely (flows through the existing empty-result path in main.py).
    trimmed_tail is the fragment removed by a partial echo-tail trim, or
    None when nothing was trimmed.
    """
    if not text or not text.strip():
        return '', None
    text = _strip_blacklist(text)
    norm = _normalize(text)
    if not norm:
        return '', None
    # Discard only a verbatim echo of the WHOLE prompt. A non-string prompt
    # (a hand-edited YAML list) disables echo detection rather than crashing.
    if isinstance(initial_prompt, str):
        prompt_norm = _normalize(initial_prompt)
        if prompt_norm and norm == prompt_norm:
            return '', None
    text, trimmed_tail = _trim_echo_tail(text, _prompt_ngrams(initial_prompt))
    return text.strip(), trimmed_tail
