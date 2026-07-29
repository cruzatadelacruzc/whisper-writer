import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from transcription_history import append_transcription


def test_appends_timestamped_line(tmp_path):
    path = tmp_path / 'hist.txt'
    result = append_transcription('informe de tórax sin hallazgos', str(path))
    assert result == str(path)
    content = path.read_text(encoding='utf-8')
    assert 'informe de tórax sin hallazgos' in content
    # Line starts with "[YYYY-MM-DD HH:MM:SS]"
    assert content.startswith('[20')
    assert '] ' in content


def test_appends_multiple_entries(tmp_path):
    path = tmp_path / 'hist.txt'
    append_transcription('primera', str(path))
    append_transcription('segunda', str(path))
    lines = path.read_text(encoding='utf-8').strip().split('\n')
    assert len(lines) == 2
    assert 'primera' in lines[0]
    assert 'segunda' in lines[1]


def test_empty_text_writes_nothing(tmp_path):
    path = tmp_path / 'hist.txt'
    assert append_transcription('', str(path)) is None
    assert append_transcription('   ', str(path)) is None
    assert not path.exists()
