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
