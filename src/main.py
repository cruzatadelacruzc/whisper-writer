import os
import sys
from audioplayer import AudioPlayer
from PyQt5.QtCore import QObject, QProcess
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QMessageBox

from key_listener import KeyListener
from result_thread import ResultThread
from ui.main_window import MainWindow
from ui.settings_window import SettingsWindow
from ui.status_window import StatusWindow
from model_load_thread import ModelLoadThread
from input_simulation import InputSimulator
from transcription_history import append_transcription
from utils import ConfigManager


class WhisperWriterApp(QObject):
    def __init__(self):
        """
        Initialize the application, opening settings window if no configuration file is found.
        """
        super().__init__()
        # Pre-set so cleanup()/restart_app() are safe even if
        # initialize_components() never ran (first run: Settings only).
        self.key_listener = None
        self.input_simulator = None
        self.components_initialized = False
        self.app = QApplication(sys.argv)
        self.app.setWindowIcon(QIcon(os.path.join('assets', 'ww-logo.png')))

        ConfigManager.initialize()

        self.settings_window = SettingsWindow()
        self.settings_window.settings_closed.connect(self.on_settings_closed)
        self.settings_window.settings_saved.connect(self.restart_app)

        if ConfigManager.config_file_exists():
            self.initialize_components()
        else:
            print('No valid configuration file found. Opening settings window...')
            self.settings_window.show()

    def initialize_components(self):
        """
        Initialize the components of the application.
        """
        self.input_simulator = InputSimulator()

        self.key_listener = KeyListener()
        self.key_listener.add_callback("on_activate", self.on_activation)
        self.key_listener.add_callback("on_deactivate", self.on_deactivation)

        model_options = ConfigManager.get_config_section('model_options')
        self.use_api = bool(model_options.get('use_api'))
        self.local_model = None
        self.model_load_thread = None

        self.result_thread = None

        self.last_transcription = ''
        self.main_window = MainWindow()
        self.main_window.openSettings.connect(self.settings_window.show)
        self.main_window.startListening.connect(self.on_start_pressed)
        self.main_window.closeApp.connect(self.exit_app)
        self.main_window.copyLast.connect(self.copy_last_transcription)

        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.status_window = StatusWindow()

        self.create_tray_icon()
        self.main_window.show()

        if self.use_api:
            self.main_window.setModelReady()
        else:
            self.main_window.setModelLoading()
            self.model_load_thread = ModelLoadThread()
            self.model_load_thread.modelReady.connect(self.on_model_ready)
            self.model_load_thread.loadFailed.connect(self.on_model_load_failed)
            self.model_load_thread.start()

        self.components_initialized = True

    def on_model_ready(self, model):
        """The background loader finished: store the model and unlock Start."""
        self.local_model = model
        self.main_window.setModelReady()

    def on_model_load_failed(self, message):
        """Loading failed: surface the error and leave Start blocked.
        Recovery path: fix Settings — saving restarts the app, retrying the load."""
        print(f'Model load failed: {message}')
        self.main_window.setModelError()
        QMessageBox.warning(self.main_window, 'WhisperWriter',
                            f'Could not load the Whisper model:\n{message}')

    def on_start_pressed(self):
        """The Start button behaves like pressing the hotkey: arm the
        listener, then run the same toggle path (start or stop recording).
        The window hides itself on click, so focus returns to the target
        app; the user stops with the hotkey (or by clicking Start again
        after reopening the window from the tray)."""
        self.key_listener.start()
        self.on_activation()

    def create_tray_icon(self):
        """
        Create the system tray icon and its context menu.
        """
        self.tray_icon = QSystemTrayIcon(QIcon(os.path.join('assets', 'ww-logo.png')), self.app)

        tray_menu = QMenu()

        show_action = QAction('WhisperWriter Main Menu', self.app)
        show_action.triggered.connect(self.main_window.show)
        tray_menu.addAction(show_action)

        settings_action = QAction('Open Settings', self.app)
        settings_action.triggered.connect(self.settings_window.show)
        tray_menu.addAction(settings_action)

        exit_action = QAction('Exit', self.app)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def cleanup(self):
        if self.key_listener:
            self.key_listener.stop()
        if self.input_simulator:
            self.input_simulator.cleanup()

    def exit_app(self):
        """
        Exit the application.
        """
        self.cleanup()
        QApplication.quit()

    def restart_app(self):
        """Restart the application to apply the new settings."""
        self.cleanup()
        QApplication.quit()
        QProcess.startDetached(sys.executable, sys.argv)

    def on_settings_closed(self):
        """
        If settings is closed without saving on first run, initialize the components with default values.
        """
        if self.components_initialized:
            return
        if not os.path.exists(os.path.join('src', 'config.yaml')):
            QMessageBox.information(
                self.settings_window,
                'Using Default Values',
                'Settings closed without saving. Default values are being used.'
            )
            self.initialize_components()

    def on_activation(self):
        """
        Called when the activation key combination is pressed.
        """
        if self.result_thread and self.result_thread.isRunning():
            recording_mode = ConfigManager.get_config_value('recording_options', 'recording_mode')
            if recording_mode == 'press_to_toggle':
                self.result_thread.stop_recording()
            elif recording_mode == 'continuous':
                self.stop_result_thread()
            return

        self.start_result_thread()

    def on_deactivation(self):
        """
        Called when the activation key combination is released.
        """
        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'hold_to_record':
            if self.result_thread and self.result_thread.isRunning():
                self.result_thread.stop_recording()

    def start_result_thread(self):
        """
        Start the result thread to record audio and transcribe it.
        """
        if self.result_thread and self.result_thread.isRunning():
            return

        # Start is disabled until the model is ready, but the hotkey can be
        # armed before that (an explicit input_backend arms it at startup):
        # without this guard a hotkey press would hand local_model=None to
        # ResultThread, which would sync-load the model inside the
        # recording thread.
        if self.local_model is None and not self.use_api:
            return

        self.result_thread = ResultThread(self.local_model)
        if not ConfigManager.get_config_value('misc', 'hide_status_window'):
            self.result_thread.statusSignal.connect(self.status_window.updateStatus)
            self.status_window.closeSignal.connect(self.stop_result_thread)
        self.result_thread.resultSignal.connect(self.on_transcription_complete)
        self.result_thread.start()

    def stop_result_thread(self):
        """
        Stop the result thread.
        """
        if self.result_thread and self.result_thread.isRunning():
            self.result_thread.stop()

    def on_transcription_complete(self, result):
        """
        When the transcription is complete, save it to the history, type the
        result, and start listening for the activation key again.
        """
        # ResultThread emits an empty string to signal a transcription error.
        # Treat it as a no-op delivery: saving it, overwriting the last
        # transcription, or typing it would clobber the clipboard and inject a
        # stray Ctrl+V. Still re-arm the hotkey so the app stays responsive.
        if not result or not result.strip():
            if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous':
                self.start_result_thread()
            else:
                self.key_listener.start()
            return

        try:
            append_transcription(result)
        except OSError as e:
            print(f'Could not save transcription history: {e}')

        self.last_transcription = result
        self.input_simulator.typewrite(result)

        if ConfigManager.get_config_value('misc', 'noise_on_completion'):
            AudioPlayer(os.path.join('assets', 'beep.wav')).play(block=True)

        if ConfigManager.get_config_value('recording_options', 'recording_mode') == 'continuous':
            self.start_result_thread()
        else:
            self.key_listener.start()

    def copy_last_transcription(self):
        """
        Copy the most recent transcription to the clipboard. Does nothing when
        there is no transcription yet, to avoid clearing the user's clipboard.
        """
        if not self.last_transcription:
            return
        QApplication.clipboard().setText(self.last_transcription)

    def run(self):
        """
        Start the application.
        """
        sys.exit(self.app.exec_())


if __name__ == '__main__':
    app = WhisperWriterApp()
    app.run()
