"""Append-only local history of transcriptions.

Protects dictated reports from being lost to power cuts or crashes: every
transcription is appended to a plain text file before it is delivered to
the active window.
"""
from datetime import datetime


def append_transcription(text, history_path='transcription_history.txt'):
    """Append a timestamped transcription to the history file.

    Returns the path written to, or None when text is empty/whitespace.
    """
    if not text or not text.strip():
        return None
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(history_path, 'a', encoding='utf-8') as f:
        f.write(f'[{timestamp}] {text.strip()}\n')
    return history_path
