from PyQt5.QtCore import QThread, pyqtSignal

from transcription import create_local_model


class ModelLoadThread(QThread):
    """
    Load the Whisper model off the GUI thread so the window stays
    responsive during the 8s-3min create_local_model() call.
    """
    modelReady = pyqtSignal(object)
    loadFailed = pyqtSignal(str)

    def run(self):
        try:
            model = create_local_model()
        except Exception as e:
            self.loadFailed.emit(str(e))
        else:
            self.modelReady.emit(model)
