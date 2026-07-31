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
from unittest.mock import patch, MagicMock, call

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


def test_on_start_pressed_arms_listener_and_runs_activation_path():
    """Start behaves like pressing the hotkey: arm + same toggle path.
    The exact call sequence matters: arming must precede the toggle."""
    fake_self = MagicMock()
    main.WhisperWriterApp.on_start_pressed(fake_self)
    assert fake_self.mock_calls == [call.key_listener.start(),
                                    call.on_activation()]


def test_on_model_ready_stores_model_and_unlocks_window():
    fake_self = MagicMock()
    model = object()
    main.WhisperWriterApp.on_model_ready(fake_self, model)
    assert fake_self.local_model is model
    fake_self.main_window.setModelReady.assert_called_once_with()


def test_on_model_load_failed_shows_error_state_and_warning():
    fake_self = MagicMock()
    with patch.object(main.QMessageBox, 'warning') as warning:
        main.WhisperWriterApp.on_model_load_failed(fake_self, 'boom')
    fake_self.main_window.setModelError.assert_called_once_with()
    warning.assert_called_once()
    assert 'boom' in warning.call_args[0][2]


def test_cleanup_tolerates_never_initialized_components():
    """First run: saving Settings triggers restart_app -> cleanup() before
    initialize_components() ever ran. __init__ now pre-sets the attributes
    to None, and cleanup's guards must accept that."""
    fake_self = MagicMock()
    fake_self.key_listener = None
    fake_self.input_simulator = None
    main.WhisperWriterApp.cleanup(fake_self)  # must not raise


def test_on_settings_closed_skips_when_already_initialized():
    """Closing Settings unsaved more than once must not initialize the
    components again (duplicate tray icon / listeners). os.path.exists is
    patched to False so the test exercises the flag, not the real
    config.yaml on this machine."""
    fake_self = MagicMock()
    fake_self.components_initialized = True
    with patch.object(main.os.path, 'exists', return_value=False), \
         patch.object(main.QMessageBox, 'information'):
        main.WhisperWriterApp.on_settings_closed(fake_self)
    fake_self.initialize_components.assert_not_called()


def test_on_settings_closed_initializes_on_first_run():
    fake_self = MagicMock()
    fake_self.components_initialized = False
    with patch.object(main.os.path, 'exists', return_value=False), \
         patch.object(main.QMessageBox, 'information'):
        main.WhisperWriterApp.on_settings_closed(fake_self)
    fake_self.initialize_components.assert_called_once_with()
