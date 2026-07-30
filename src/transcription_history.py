"""Append-only local history of transcriptions.

Protects dictated reports from being lost to power cuts or crashes: every
transcription is appended to a plain text file before it is delivered to
the active window.
"""
import os
from datetime import datetime


def append_transcription(text, history_path='transcription_history.txt'):
    """Append a timestamped transcription to the history file.

    Returns the path written to, or None when text is empty/whitespace.

    The file may contain sensitive dictated content, so it is created with
    0600 permissions (owner read/write only). os.open honours the mode only
    when it creates the file; an existing file keeps its current permissions.
    """
    if not text or not text.strip():
        return None
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    fd = os.open(history_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as f:
        f.write(f'[{timestamp}] {text.strip()}\n')
    return history_path
