import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def _fake_evdev(devices):
    fake = MagicMock()
    fake.list_devices.return_value = devices
    return fake


def test_evdev_backend_unavailable_when_no_accessible_devices():
    """
    A user without read permission on /dev/input/event* gets an empty
    list_devices(); the backend would listen to nothing, so auto-selection
    must skip it and fall back to pynput.
    """
    import key_listener
    with patch.dict(sys.modules, {'evdev': _fake_evdev([])}):
        assert key_listener.EvdevBackend.is_available() is False


def test_evdev_backend_available_with_accessible_devices():
    import key_listener
    with patch.dict(sys.modules, {'evdev': _fake_evdev(['/dev/input/event0'])}):
        assert key_listener.EvdevBackend.is_available() is True


def test_evdev_backend_unavailable_when_import_fails():
    import key_listener
    with patch.dict(sys.modules, {'evdev': None}):
        assert key_listener.EvdevBackend.is_available() is False


def test_evdev_backend_instantiates_without_module_scope_evdev():
    """
    EvdevBackend.__init__ evaluates runtime annotations (List, evdev.InputDevice)
    and uses a function-local evdev import; regression for the NameError that
    crashed instantiation when evdev names were missing at module scope.
    """
    import key_listener
    with patch.dict(sys.modules, {'evdev': _fake_evdev(['/dev/input/event0'])}):
        backend = key_listener.EvdevBackend()
        assert backend is not None
