"""MainWindow model-state methods. Needs real widgets, so a QApplication is
created on the offscreen platform. If the platform cannot initialize in this
environment (spec allows it), the module is skipped — the states are also
exercised live during verification."""
import os
import sys

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from PyQt5.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
except Exception as e:  # offscreen platform unavailable
    pytest.skip(f'offscreen QApplication unavailable: {e}', allow_module_level=True)


@pytest.fixture()
def window():
    from ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_set_model_loading_disables_start(window):
    window.setModelLoading()
    assert window.model_status_label.text() == 'Loading model…'
    assert window.start_btn.isEnabled() is False


def test_set_model_ready_enables_start(window):
    window.setModelLoading()
    window.setModelReady()
    assert window.model_status_label.text() == 'Model ready'
    assert window.start_btn.isEnabled() is True


def test_set_model_error_disables_start(window):
    window.setModelReady()
    window.setModelError()
    assert window.model_status_label.text() == 'Model load failed — check Settings'
    assert window.start_btn.isEnabled() is False


def test_start_button_disabled_at_construction(window):
    """No race window between show() and setModelLoading(): the button is
    born disabled and only the state methods enable it."""
    assert window.start_btn.isEnabled() is False
