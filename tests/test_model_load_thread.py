"""ModelLoadThread unit tests. run() is called directly (no real thread,
no QApplication, no event loop): pyqtSignal delivers synchronously to
directly-connected Python callables."""
import os
import sys
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def test_model_ready_emitted_with_the_loaded_model():
    import model_load_thread
    fake_model = object()
    received = []
    thread = model_load_thread.ModelLoadThread()
    thread.modelReady.connect(received.append)
    thread.loadFailed.connect(lambda msg: received.append(('FAILED', msg)))
    with patch.object(model_load_thread, 'create_local_model', return_value=fake_model):
        thread.run()
    assert received == [fake_model]


def test_load_failed_emitted_with_the_error_message():
    import model_load_thread
    received = []
    thread = model_load_thread.ModelLoadThread()
    thread.modelReady.connect(lambda m: received.append(('READY', m)))
    thread.loadFailed.connect(received.append)
    with patch.object(model_load_thread, 'create_local_model',
                      side_effect=RuntimeError('corrupt cache')):
        thread.run()
    assert received == ['corrupt cache']
