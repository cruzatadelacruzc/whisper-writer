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


def test_short_prompt_whole_prompt_fallback():
    """A prompt with fewer than MIN_ECHO_TERMS terms still catches echoes
    via the whole-prompt entry in the ngram set."""
    short_prompt = 'silueta cardiomediastínica, trama broncovascular'
    # Full echo of the whole (2-term) prompt is discarded...
    assert filter_transcription(
        'Silueta cardiomediastínica, trama broncovascular.', short_prompt) == ''
    # ...and a trailing echo of it is trimmed off real text.
    assert filter_transcription(
        'Sin hallazgos agudos. Silueta cardiomediastínica, trama broncovascular',
        short_prompt) == 'Sin hallazgos agudos.'


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
