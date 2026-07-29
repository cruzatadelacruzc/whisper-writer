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
        Deliver the text instantly: copy it to the clipboard, simulate
        Ctrl+V, then restore the previous clipboard contents.

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
            previous = clipboard.text()
            clipboard.setText(text)
            _process_qt_events()
        except Exception as e:
            print(f'Clipboard unavailable ({e}); falling back to typing.')
            self._typewrite_pynput(text, interval)
            return

        # Phase 2: Perform the key events. Catch exceptions but don't retry.
        try:
            from pynput.keyboard import Key
            time.sleep(0.05)
            with self.keyboard.pressed(Key.ctrl):
                self.keyboard.press('v')
                self.keyboard.release('v')
            # Give the target application time to read the clipboard
            # before restoring the previous contents.
            time.sleep(0.3)
        except Exception as e:
            print(f'Paste keystroke failed ({e}); transcription is in the history file.')
        finally:
            # Phase 3: Always restore the previous clipboard, catch and ignore
            # any exceptions from this cleanup.
            try:
                clipboard.setText(previous)
                _process_qt_events()
            except Exception:
                pass

    def cleanup(self):
        """
        Perform cleanup operations, such as terminating the dotool process.
        """
        if self.input_method == 'dotool':
            self._terminate_dotool()
