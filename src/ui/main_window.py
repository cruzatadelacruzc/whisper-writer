import os
import sys
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QPushButton, QHBoxLayout, QLabel
from PyQt5.QtCore import Qt, pyqtSignal

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from ui.base_window import BaseWindow

class MainWindow(BaseWindow):
    openSettings = pyqtSignal()
    startListening = pyqtSignal()
    closeApp = pyqtSignal()
    copyLast = pyqtSignal()

    def __init__(self):
        """
        Initialize the main window.
        """
        super().__init__('WhisperWriter', 460, 180)
        self.initMainUI()

    def initMainUI(self):
        """
        Initialize the main user interface.
        """
        self.start_btn = QPushButton('Start')
        self.start_btn.setFont(QFont('Segoe UI', 10))
        self.start_btn.setFixedSize(120, 60)
        self.start_btn.clicked.connect(self.startPressed)

        settings_btn = QPushButton('Settings')
        settings_btn.setFont(QFont('Segoe UI', 10))
        settings_btn.setFixedSize(120, 60)
        settings_btn.clicked.connect(self.openSettings.emit)

        copy_btn = QPushButton('Copy Last')
        copy_btn.setFont(QFont('Segoe UI', 10))
        copy_btn.setFixedSize(120, 60)
        copy_btn.clicked.connect(self.copyLast.emit)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.start_btn)
        button_layout.addWidget(settings_btn)
        button_layout.addWidget(copy_btn)
        button_layout.addStretch(1)

        self.model_status_label = QLabel('')
        self.model_status_label.setFont(QFont('Segoe UI', 10))
        self.model_status_label.setAlignment(Qt.AlignCenter)
        self.model_status_label.setStyleSheet('color: #404040;')

        self.main_layout.addStretch(1)
        self.main_layout.addLayout(button_layout)
        self.main_layout.addWidget(self.model_status_label)
        self.main_layout.addStretch(1)

    def closeEvent(self, event):
        """
        Close the application when the main window is closed.
        """
        self.closeApp.emit()

    def startPressed(self):
        """
        Emit the startListening signal when the start button is pressed.
        """
        self.startListening.emit()
        self.hide()

    def setModelLoading(self):
        """Model is loading in the background: block Start, show progress text."""
        self.model_status_label.setText('Loading model…')
        self.start_btn.setEnabled(False)

    def setModelReady(self):
        """Model (or API mode) is ready: allow Start."""
        self.model_status_label.setText('Model ready')
        self.start_btn.setEnabled(True)

    def setModelError(self):
        """Model load failed: keep Start blocked; Settings is the way out."""
        self.model_status_label.setText('Model load failed — check Settings')
        self.start_btn.setEnabled(False)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
