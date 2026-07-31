"""Guards in main.py against destructive empty transcription results.

main.py pulls in display/hardware deps (pynput, audioplayer) at import time,
so those are stubbed before importing it. The two guard methods are then
exercised as unbound functions over a MagicMock ``self`` — no QApplication or
graphical session required, so the suite stays headless.
"""
import os
import sys
import types
import warnings
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _install_stubs():
    if 'audioplayer' not in sys.modules:
        ap = types.ModuleType('audioplayer')
        ap.AudioPlayer = MagicMock()
        sys.modules['audioplayer'] = ap
    if 'pynput' not in sys.modules:
        pk = types.ModuleType('pynput.keyboard')
        pk.Controller = MagicMock()
        pk.Key = type('Key', (), {'ctrl': object()})
        pp = types.ModuleType('pynput')
        pp.keyboard = pk
        sys.modules['pynput'] = pp
        sys.modules['pynput.keyboard'] = pk


_install_stubs()
# Importing main pulls in webrtcvad, whose expected/harmless "pkg_resources is
# deprecated" warning would otherwise clutter the test output. Suppress it at
# import time so the suite output stays pristine.
with warnings.catch_warnings():
    warnings.simplefilter('ignore')
    import main  # noqa: E402


def _config(noise=False, recording_mode='press_to_toggle'):
    return lambda section, key: {
        'noise_on_completion': noise,
        'recording_mode': recording_mode,
    }[key]


def test_copy_last_transcription_empty_does_not_touch_clipboard():
    fake_self = MagicMock()
    fake_self.last_transcription = ''
    with patch.object(main.QApplication, 'clipboard') as clipboard:
        main.WhisperWriterApp.copy_last_transcription(fake_self)
    # The clipboard must not be cleared when there is nothing to copy.
    clipboard.assert_not_called()


def test_copy_last_transcription_copies_when_present():
    fake_self = MagicMock()
    fake_self.last_transcription = 'informe de torax'
    with patch.object(main.QApplication, 'clipboard') as clipboard:
        main.WhisperWriterApp.copy_last_transcription(fake_self)
    clipboard.return_value.setText.assert_called_once_with('informe de torax')


def test_empty_result_is_not_delivered_and_rearms_hotkey():
    fake_self = MagicMock()
    fake_self.last_transcription = 'SENTINEL'
    with patch.object(main, 'append_transcription') as append, \
         patch.object(main.ConfigManager, 'get_config_value',
                      side_effect=_config()):
        main.WhisperWriterApp.on_transcription_complete(fake_self, '')

    # Nothing was saved, delivered, or overwritten...
    append.assert_not_called()
    fake_self.input_simulator.typewrite.assert_not_called()
    assert fake_self.last_transcription == 'SENTINEL'
    # ...but the hotkey was re-armed so the app stays responsive.
    fake_self.key_listener.start.assert_called_once()


def test_whitespace_result_is_not_delivered():
    fake_self = MagicMock()
    fake_self.last_transcription = 'SENTINEL'
    with patch.object(main, 'append_transcription') as append, \
         patch.object(main.ConfigManager, 'get_config_value',
                      side_effect=_config()):
        main.WhisperWriterApp.on_transcription_complete(fake_self, '   \n ')

    append.assert_not_called()
    fake_self.input_simulator.typewrite.assert_not_called()
    assert fake_self.last_transcription == 'SENTINEL'
    fake_self.key_listener.start.assert_called_once()


def test_valid_result_is_delivered_and_saved():
    fake_self = MagicMock()
    fake_self.last_transcription = ''
    with patch.object(main, 'append_transcription') as append, \
         patch.object(main.ConfigManager, 'get_config_value',
                      side_effect=_config()):
        main.WhisperWriterApp.on_transcription_complete(fake_self, 'hola mundo')

    append.assert_called_once_with('hola mundo')
    fake_self.input_simulator.typewrite.assert_called_once_with('hola mundo')
    assert fake_self.last_transcription == 'hola mundo'
    fake_self.key_listener.start.assert_called_once()


def test_start_result_thread_returns_early_when_model_not_loaded():
    """Local mode with the model still loading: start_result_thread must not
    build a ResultThread (transcribe_local would otherwise sync-load the
    model inside the recording thread)."""
    self_mock = MagicMock()
    self_mock.result_thread = None
    self_mock.local_model = None
    self_mock.use_api = False
    with patch.object(main, 'ResultThread') as result_thread_cls:
        main.WhisperWriterApp.start_result_thread(self_mock)
    result_thread_cls.assert_not_called()
