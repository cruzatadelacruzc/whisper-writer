import subprocess
import os
import signal
import time

from utils import ConfigManager


def _get_clipboard():
    """Return the Qt clipboard of the running application."""
    from PyQt5.QtWidgets import QApplication
    return QApplication.clipboard()


def _process_qt_events():
    from PyQt5.QtWidgets import QApplication
    QApplication.processEvents()


def _single_shot(delay_ms, callback):
    """Schedule ``callback`` to run on the Qt event loop after ``delay_ms``.

    Wrapped in a module-level helper (same patchable pattern as
    ``_get_clipboard``/``_process_qt_events``) so tests can fire the callback
    synchronously instead of waiting on a real timer.
    """
    from PyQt5.QtCore import QTimer
    QTimer.singleShot(delay_ms, callback)


def _clone_mimedata(source):
    """Return a standalone QMimeData deep-copying every format of ``source``.

    The clipboard invalidates the QMimeData object it hands out once its
    ownership changes, so each format's bytes are copied eagerly into a new
    object that outlives the original. This preserves non-text content (e.g.
    an image) across the snapshot -> restore cycle.
    """
    from PyQt5.QtCore import QMimeData, QByteArray
    clone = QMimeData()
    if source is not None:
        for fmt in source.formats():
            clone.setData(fmt, QByteArray(source.data(fmt)))
    return clone


def run_command_or_exit_on_failure(command):
    """
    Run a shell command and exit if it fails.

    Args:
        command (list): The command to run as a list of strings.
    """
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e}")
        exit(1)

class InputSimulator:
    """
    A class to simulate keyboard input using various methods.
    """

    def __init__(self):
        """
        Initialize the InputSimulator with the specified configuration.
        """
        self.input_method = ConfigManager.get_config_value('post_processing', 'input_method')
        self.dotool_process = None
        # Deferred-restore bookkeeping for the clipboard method.
        self._paste_seq = 0
        self._pending_restore_mime = None

        if self.input_method in ('pynput', 'clipboard'):
            from pynput.keyboard import Controller as PynputController
            self.keyboard = PynputController()
        elif self.input_method == 'dotool':
            self._initialize_dotool()

    def _initialize_dotool(self):
        """
        Initialize the dotool process for input simulation.
        """
        self.dotool_process = subprocess.Popen("dotool", stdin=subprocess.PIPE, text=True)
        assert self.dotool_process.stdin is not None

    def _terminate_dotool(self):
        """
        Terminate the dotool process if it's running.
        """
        if self.dotool_process:
            os.kill(self.dotool_process.pid, signal.SIGINT)
            self.dotool_process = None

    def typewrite(self, text):
        """
        Simulate typing the given text with the specified interval between keystrokes.

        Args:
            text (str): The text to type.
        """
        interval = ConfigManager.get_config_value('post_processing', 'writing_key_press_delay')
        if self.input_method == 'pynput':
            self._typewrite_pynput(text, interval)
        elif self.input_method == 'clipboard':
            self._paste_via_clipboard(text, interval)
        elif self.input_method == 'ydotool':
            self._typewrite_ydotool(text, interval)
        elif self.input_method == 'dotool':
            self._typewrite_dotool(text, interval)

    def _typewrite_pynput(self, text, interval):
        """
        Simulate typing using pynput.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        for char in text:
            self.keyboard.press(char)
            self.keyboard.release(char)
            time.sleep(interval)

    def _typewrite_ydotool(self, text, interval):
        """
        Simulate typing using ydotool.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        cmd = "ydotool"
        run_command_or_exit_on_failure([
            cmd,
            "type",
            "--key-delay",
            str(interval * 1000),
            "--",
            text,
        ])

    def _typewrite_dotool(self, text, interval):
        """
        Simulate typing using dotool.

        Args:
            text (str): The text to type.
            interval (float): The interval between keystrokes in seconds.
        """
        assert self.dotool_process and self.dotool_process.stdin
        self.dotool_process.stdin.write(f"typedelay {interval * 1000}\n")
        self.dotool_process.stdin.write(f"type {text}\n")
        self.dotool_process.stdin.flush()

    def _paste_via_clipboard(self, text, interval):
        """
        Deliver the text instantly: copy it to the clipboard and simulate
        Ctrl+V, then restore the previous clipboard about a second later via
        a deferred single-shot timer.

        The restore is deferred (not done inline) because setting the
        clipboard makes this application the X11 selection owner: it must keep
        serving the target's paste request through the Qt event loop after
        Ctrl+V. Restoring synchronously would answer that still-pending
        request with the old data, pasting stale text into the document.

        The previous clipboard is snapshotted as a full QMimeData clone, so
        non-text content (e.g. an image) survives the round-trip. A sequence
        token guards rapid consecutive dictations: only the most recent
        paste's deferred restore runs, and it restores the original
        pre-dictation clipboard rather than an intervening transcription.

        Falls back to typing only when the clipboard could not be prepared;
        a failure after that point must not re-type (the paste may already
        have been delivered) — the previous clipboard is still restored.

        Args:
            text (str): The text to paste.
            interval (float): Keystroke interval used only by the fallback.
        """
        # Phase 1: Prepare the clipboard. Fall back to typing only if this fails.
        try:
            clipboard = _get_clipboard()
            if self._pending_restore_mime is not None:
                # A previous restore is still pending, so the clipboard holds
                # the prior transcription, not the user's content. Reuse the
                # stored original snapshot instead of capturing that.
                previous = self._pending_restore_mime
            else:
                previous = _clone_mimedata(clipboard.mimeData())
            clipboard.setText(text)
            _process_qt_events()
            self._pending_restore_mime = previous
        except Exception as e:
            print(f'Clipboard unavailable ({e}); falling back to typing.')
            self._typewrite_pynput(text, interval)
            return

        # Each paste claims a fresh token; only the latest paste's deferred
        # restore will actually run (see _restore below).
        self._paste_seq += 1
        token = self._paste_seq

        # Phase 2: Perform the key events. Catch exceptions but don't retry.
        try:
            from pynput.keyboard import Key
            time.sleep(0.05)
            with self.keyboard.pressed(Key.ctrl):
                self.keyboard.press('v')
                self.keyboard.release('v')
        except Exception as e:
            print(f'Paste keystroke failed ({e}); transcription is in the history file.')

        # Phase 3: Schedule the restore of the previous clipboard. Deferred so
        # the target has time to serve its paste from the transcription first;
        # scheduled even when the keystroke above failed.
        def _restore(token=token, previous=previous):
            if self._paste_seq != token:
                # A newer paste superseded this one; it owns the restore now.
                return
            try:
                clipboard.setMimeData(previous)
                _process_qt_events()
                self._pending_restore_mime = None
            except Exception as e:
                print(f'Could not restore previous clipboard ({e}); '
                      'sensitive text may remain on the clipboard.')

        _single_shot(1000, _restore)

    def cleanup(self):
        """
        Perform cleanup operations, such as terminating the dotool process.
        """
        if self.input_method == 'dotool':
            self._terminate_dotool()
