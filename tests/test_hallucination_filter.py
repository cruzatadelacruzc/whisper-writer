"""Anti-hallucination filter: known stock phrases and a verbatim echo of the
whole initial_prompt must never reach delivery or the medical history file
(spec: 2026-07-31-hallucination-filter-and-start-design; safety rework
2026-08-01-filter-safety-rework-HANDOFF). Pure string tests.

Safety stance (medical dictation): the filter only removes text it can be sure
is model-inserted — a stock phrase that is the WHOLE utterance or a TRAILING
tail, or an echo of the WHOLE prompt. It never cuts mid-word, mid-sentence, or a
partial prompt run, because the prompt lists the same anatomical terms a
radiologist dictates. A partial trailing prompt echo IS trimmed, but only
when a sentence boundary precedes it in the original text (see the
sentence-boundary-guarded cases below).

filter_transcription returns (cleaned_text, trimmed_tail): trimmed_tail is
the exact fragment cut by a partial trim, or None when nothing was
trimmed."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hallucination_filter import filter_transcription  # noqa: E402

# The user's real list-shaped prompt (9 comma-separated radiology terms).
PROMPT = ('Radiografía de tórax, silueta cardiomediastínica, trama '
          'broncovascular, consolidación, derrame pleural, neumotórax, '
          'campos pulmonares, estructuras óseas, impresión diagnóstica.')


# --- Blacklist: whole-utterance or trailing tail only, word-bounded ---

def test_amara_exact_is_discarded():
    assert filter_transcription(
        'Subtítulos por la comunidad de Amara.org', PROMPT) == ('', None)


def test_amara_variants_are_discarded():
    # Casing, accents and punctuation must not matter.
    assert filter_transcription(
        ' subtitulos por la comunidad de amara org ', PROMPT) == ('', None)
    assert filter_transcription(
        'Subtitulado por la comunidad de Amara.org.', PROMPT) == ('', None)
    assert filter_transcription(
        'Subtítulos realizados por la comunidad de Amara.org', PROMPT) == ('', None)


def test_gracias_por_ver_is_discarded():
    assert filter_transcription('¡Gracias por ver el vídeo!', PROMPT) == ('', None)
    assert filter_transcription('Gracias por ver.', PROMPT) == ('', None)


def test_two_hallucinations_together_are_discarded():
    assert filter_transcription(
        'Subtítulos por la comunidad de Amara.org ¡Gracias por ver el vídeo!',
        PROMPT) == ('', None)


def test_hallucination_after_real_text_is_stripped():
    assert filter_transcription(
        'Consolidación en lóbulo superior derecho. '
        'Subtítulos por la comunidad de Amara.org',
        PROMPT) == ('Consolidación en lóbulo superior derecho.', None)


def test_longest_phrase_wins_no_leftover_fragment():
    # "Gracias por ver" is a prefix of "¡Gracias por ver el vídeo!": the
    # longer phrase must be removed as a whole, not leave "el vídeo" behind.
    assert filter_transcription(
        'Informe listo. ¡Gracias por ver el vídeo!', PROMPT) == ('Informe listo.', None)


def test_blacklist_does_not_match_mid_word():
    # Finding 1: "gracias por ver" must NOT match inside "verificar"/"verla".
    assert filter_transcription(
        'Gracias por verificar la imagen.', PROMPT) == \
        ('Gracias por verificar la imagen.', None)
    assert filter_transcription(
        'Le damos las gracias por verla.', PROMPT) == \
        ('Le damos las gracias por verla.', None)


def test_blacklist_does_not_eat_clinical_phrase_mid_sentence():
    # Finding 2: a legit clinical use of "gracias por ver" mid-sentence stays.
    assert filter_transcription(
        'Muchas gracias por ver al paciente.', PROMPT) == \
        ('Muchas gracias por ver al paciente.', None)
    assert filter_transcription(
        'Gracias por ver el estudio previo comparativo.', PROMPT) == \
        ('Gracias por ver el estudio previo comparativo.', None)


# --- Prompt echo: only a verbatim echo of the WHOLE prompt is discarded ---

def test_whole_prompt_echo_is_discarded():
    assert filter_transcription(PROMPT, PROMPT) == ('', None)


def test_three_term_subrun_is_kept():
    # Finding 3: the first three prompt terms are ALSO a plausible dictation,
    # so a partial run is never discarded — only the whole prompt is.
    text = ('Radiografía de tórax, silueta cardiomediastínica, '
            'trama broncovascular.')
    assert filter_transcription(text, PROMPT) == (text, None)


def test_negative_findings_enumeration_is_kept_intact():
    # Finding 3, the dangerous case: these ARE the prompt's consecutive terms,
    # but as a real negative-findings dictation. Trimming would invert/erase
    # the clinical meaning, so they must survive untouched.
    assert filter_transcription(
        'Consolidación, derrame pleural, neumotórax.', PROMPT) == \
        ('Consolidación, derrame pleural, neumotórax.', None)
    assert filter_transcription(
        'Sin consolidación, derrame pleural, neumotórax.', PROMPT) == \
        ('Sin consolidación, derrame pleural, neumotórax.', None)
    assert filter_transcription(
        'No se observa consolidación, derrame pleural, neumotórax.', PROMPT) == \
        ('No se observa consolidación, derrame pleural, neumotórax.', None)


def test_trailing_echo_after_period_is_trimmed_with_notice():
    # The trim deferred in PR #9 now ships: a real sentence ending in '.'
    # followed by a verbatim run of >=3 consecutive prompt terms is cut,
    # and the cut fragment is reported so the caller can notify the user.
    text = ('Estudio dentro de límites normales. Consolidación, derrame '
            'pleural, neumotórax, campos pulmonares')
    assert filter_transcription(text, PROMPT) == (
        'Estudio dentro de límites normales.',
        'Consolidación, derrame pleural, neumotórax, campos pulmonares')


def test_trim_rejected_when_head_too_short():
    # A period precedes the echoed run, but the head would be too short
    # (<=2 words) to safely deliver alone, so the trim is rejected.
    text = 'Bien. Consolidación, derrame pleural, neumotórax.'
    assert filter_transcription(text, PROMPT) == (text, None)


def test_trim_rejected_when_head_ends_in_dangling_negation():
    # Even with a sentence boundary before the echo, a head ending in a
    # dangling negation/preposition is not a safe sentence on its own.
    text = 'Hallazgo relevante sin. Consolidación, derrame pleural, neumotórax.'
    assert filter_transcription(text, PROMPT) == (text, None)


def test_trim_rejected_when_match_is_whole_text():
    # No character precedes the echoed run at all (it IS the whole text),
    # so there is no sentence boundary to satisfy — never trimmed.
    text = 'Consolidación, derrame pleural, neumotórax, campos pulmonares'
    assert filter_transcription(text, PROMPT) == (text, None)


def test_trim_rejected_when_tail_contains_internal_sentence_boundary():
    # Real positive findings dictated as separate short sentences must
    # never be silently cut just because they line up with consecutive
    # prompt terms. A trailing '.' alone is fine (that's the shipped
    # comma-enumerated case); a '.'/';' INSIDE the tail means these are
    # separate sentences, not one enumeration, and must survive intact.
    text = ('Hay hallazgos relevantes. Consolidación. Derrame pleural. '
            'Neumotórax.')
    assert filter_transcription(text, PROMPT) == (text, None)


def test_real_dictation_is_untouched():
    text = 'Se observa consolidación basal derecha sin derrame pleural.'
    assert filter_transcription(text, PROMPT) == (text, None)


def test_dictation_with_connectors_is_not_an_echo():
    # Contains prompt terms, but with the speaker's own connective words.
    text = ('Se observa consolidación basal derecha sin derrame pleural '
            'ni neumotórax.')
    assert filter_transcription(text, PROMPT) == (text, None)


def test_short_dictation_is_never_discarded():
    assert filter_transcription('Derrame pleural.', PROMPT) == ('Derrame pleural.', None)
    assert filter_transcription(
        'derrame pleural, neumotórax', PROMPT) == ('derrame pleural, neumotórax', None)


def test_empty_and_whitespace_input():
    assert filter_transcription('', PROMPT) == ('', None)
    assert filter_transcription('   \n ', PROMPT) == ('', None)
    assert filter_transcription(None, PROMPT) == ('', None)


# --- Prompt shape / robustness ---

def test_none_prompt_disables_echo_but_keeps_blacklist():
    assert filter_transcription('¡Gracias por ver el vídeo!', None) == ('', None)
    assert filter_transcription(PROMPT, None) == (PROMPT, None)


def test_list_shaped_prompt_fails_open():
    # A hand-edited YAML list reaches the filter as a list, not a str. The
    # filter must fail open (no crash, echo detection simply off), never wipe
    # every transcription. (Minor from the final review.)
    assert filter_transcription(
        'Radiografía de tórax normal.',
        ['consolidación', 'derrame pleural', 'neumotórax']) == \
        ('Radiografía de tórax normal.', None)


def test_short_prompt_whole_echo_is_discarded():
    # A prompt with only two terms: a verbatim echo of the whole prompt is
    # still discarded; a trailing partial echo is kept (trim deferred).
    short_prompt = 'silueta cardiomediastínica, trama broncovascular'
    assert filter_transcription(
        'Silueta cardiomediastínica, trama broncovascular.', short_prompt) == ('', None)
    kept = 'Sin hallazgos agudos. Silueta cardiomediastínica, trama broncovascular'
    assert filter_transcription(kept, short_prompt) == (kept, None)


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
            'Subtítulos por la comunidad de Amara.org') == ('', None)
        # Real text still gets the normal post-processing (trailing space).
        assert transcription.post_process_transcription(
            'Sin hallazgos agudos.') == ('Sin hallazgos agudos. ', None)
        # Echo-dependent case: a verbatim echo of the WHOLE configured prompt
        # is discarded — proves the configured initial_prompt reaches the
        # filter (with a hardcoded None the echo would be delivered).
        assert transcription.post_process_transcription(PROMPT) == ('', None)
