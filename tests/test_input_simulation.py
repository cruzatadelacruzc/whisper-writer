import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


# Create fake Key object for tests that need it
class FakeKey:
    """Fake pynput.keyboard.Key for use in tests."""
    class _KeyEnum:
        """Fake enum for Key values."""
        ctrl = object()

    # Make it work as both a module-like object and with attribute access
    ctrl = _KeyEnum.ctrl


class FakeMimeData:
    """Minimal stand-in for QMimeData used to snapshot the clipboard."""

    def __init__(self, data=None):
        self._data = {k: bytes(v) for k, v in (data or {}).items()}

    def formats(self):
        return list(self._data.keys())

    def data(self, fmt):
        return self._data.get(fmt, b'')

    def setData(self, fmt, value):
        self._data[fmt] = bytes(value)

    def text(self):
        raw = self._data.get('text/plain')
        return raw.decode('utf-8') if raw is not None else ''


class FakeClipboard:
    """Fake QClipboard that tracks text history and full MIME contents.

    ``history`` records every ``setText`` call (used by the older tests);
    ``mimeData``/``setMimeData`` mirror the real clipboard API the deferred
    restore relies on so non-text formats can be exercised.
    """

    def __init__(self, initial='previous content'):
        self._mime = FakeMimeData({'text/plain': initial.encode('utf-8')})
        self.history = [initial]

    def set_mime(self, data):
        """Test helper: seed the clipboard with arbitrary MIME formats."""
        self._mime = FakeMimeData(data)

    def text(self):
        return self._mime.text()

    def setText(self, t):
        self._mime = FakeMimeData({'text/plain': t.encode('utf-8')})
        self.history.append(t)

    def mimeData(self):
        return self._mime

    def setMimeData(self, mime):
        self._mime = mime


class FakeKeyboard:
    """Records pynput calls. Supports the pressed() context manager."""
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(('press', key))

    def release(self, key):
        self.events.append(('release', key))

    def pressed(self, key):
        kb = self
        class _Ctx:
            def __enter__(self):
                kb.events.append(('hold', key))
                return self
            def __exit__(self, *a):
                kb.events.append(('unhold', key))
        return _Ctx()


class _FakePynputSetup:
    """Context manager to set up and tear down fake pynput modules."""

    def __enter__(self):
        fake_pynput_keyboard = MagicMock()
        fake_pynput_keyboard.Controller = FakeKeyboard
        fake_pynput_keyboard.Key = FakeKey

        fake_pynput = MagicMock()
        fake_pynput.keyboard = fake_pynput_keyboard

        self.old_pynput = sys.modules.get('pynput')
        self.old_pynput_keyboard = sys.modules.get('pynput.keyboard')
        sys.modules['pynput'] = fake_pynput
        sys.modules['pynput.keyboard'] = fake_pynput_keyboard
        return self

    def __exit__(self, *args):
        if self.old_pynput is None:
            sys.modules.pop('pynput', None)
        else:
            sys.modules['pynput'] = self.old_pynput
        if self.old_pynput_keyboard is None:
            sys.modules.pop('pynput.keyboard', None)
        else:
            sys.modules['pynput.keyboard'] = self.old_pynput_keyboard


def make_simulator(fake_keyboard):
    """Build an InputSimulator configured for the clipboard method."""
    import input_simulation
    with patch.object(input_simulation.ConfigManager, 'get_config_value',
                      side_effect=lambda section, key: {
                          'input_method': 'clipboard',
                          'writing_key_press_delay': 0,
                      }[key]):
        sim = input_simulation.InputSimulator()
    # The constructor already set self.keyboard to a FakeKeyboard instance;
    # replace it with the one we want to inspect.
    sim.keyboard = fake_keyboard
    return sim


def _fire_immediately(delay_ms, callback):
    """_single_shot replacement that runs the callback synchronously."""
    callback()


def test_clipboard_paste_sets_text_and_restores_previous():
    with _FakePynputSetup():
        import input_simulation
        from pynput.keyboard import Key
        fake_clip = FakeClipboard('previous content')
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          return_value='clipboard'), \
             patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
             patch.object(input_simulation, '_process_qt_events'), \
             patch.object(input_simulation, '_single_shot', side_effect=_fire_immediately), \
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('texto del informe')

        # The transcription was placed on the clipboard, then the previous
        # content was restored afterwards (the deferred timer fired inline).
        assert 'texto del informe' in fake_clip.history
        assert fake_clip.text() == 'previous content'
        # Ctrl was held while v was pressed.
        assert ('hold', Key.ctrl) in fake_kb.events
        assert ('press', 'v') in fake_kb.events


def test_clipboard_failure_falls_back_to_typing():
    with _FakePynputSetup():
        import input_simulation
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        def boom():
            raise RuntimeError('no clipboard')

        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          side_effect=lambda section, key: {
                              'input_method': 'clipboard',
                              'writing_key_press_delay': 0,
                          }[key]), \
             patch.object(input_simulation, '_get_clipboard', side_effect=boom), \
             patch.object(input_simulation, '_single_shot', side_effect=_fire_immediately), \
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('ab')

        # Fallback typed the text character by character.
        assert ('press', 'a') in fake_kb.events
        assert ('press', 'b') in fake_kb.events


def test_clipboard_key_press_failure_restores_without_typing():
    """
    When the key press fails AFTER clipboard setup, the previous clipboard
    is restored, and NO typing fallback occurs (the paste may already have
    been delivered to the target).
    """
    with _FakePynputSetup():
        import input_simulation
        fake_clip = FakeClipboard('previous content')
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        # Create a FakeKeyboard that fails on pressed() call.
        class FailingKeyboard(FakeKeyboard):
            def pressed(self, key):
                raise RuntimeError('keyboard connection lost')

        sim.keyboard = FailingKeyboard()

        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          return_value='clipboard'), \
             patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
             patch.object(input_simulation, '_process_qt_events'), \
             patch.object(input_simulation, '_single_shot', side_effect=_fire_immediately), \
             patch.object(input_simulation.time, 'sleep'):
            # This should not raise; it should handle the failure gracefully.
            sim.typewrite('test text')

        # The text was placed on the clipboard and then restored.
        assert 'test text' in fake_clip.history
        assert fake_clip.text() == 'previous content'
        # No per-character typing occurred (no fallback after clipboard setup).
        assert ('press', 't') not in sim.keyboard.events
        assert ('press', 'e') not in sim.keyboard.events


def test_clipboard_restore_is_deferred_until_timer_fires():
    """The restore must NOT happen inline: while the target serves its paste
    request through the Qt event loop, the transcription has to stay on the
    clipboard. It is only restored when the deferred single-shot fires."""
    with _FakePynputSetup():
        import input_simulation
        fake_clip = FakeClipboard('previous content')
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        scheduled = []
        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          return_value='clipboard'), \
             patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
             patch.object(input_simulation, '_process_qt_events'), \
             patch.object(input_simulation, '_single_shot',
                          side_effect=lambda d, cb: scheduled.append((d, cb))), \
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('texto del informe')

            # Restore is still pending: the transcription remains on the
            # clipboard so the target can paste it.
            assert fake_clip.text() == 'texto del informe'
            assert len(scheduled) == 1
            delay, callback = scheduled[0]
            assert delay == 1000

            # The deferred timer fires: previous content is restored now.
            callback()
            assert fake_clip.text() == 'previous content'


def test_token_guard_stale_restore_does_not_clobber_and_restores_original():
    """Two rapid dictations: firing the FIRST paste's (now stale) restore
    must not clobber the second transcription, and the surviving restore must
    return the ORIGINAL pre-dictation clipboard, not the first transcription."""
    with _FakePynputSetup():
        import input_simulation
        fake_clip = FakeClipboard('ORIGINAL')
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        scheduled = []
        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          return_value='clipboard'), \
             patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
             patch.object(input_simulation, '_process_qt_events'), \
             patch.object(input_simulation, '_single_shot',
                          side_effect=lambda d, cb: scheduled.append(cb)), \
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('T1')
            sim.typewrite('T2')

            # Both restores pending; clipboard currently holds T2.
            assert fake_clip.text() == 'T2'
            assert len(scheduled) == 2

            # Fire the FIRST (stale) restore: it is superseded and must be a
            # no-op — T2 stays on the clipboard.
            scheduled[0]()
            assert fake_clip.text() == 'T2'

            # Fire the SECOND (current) restore: it restores the ORIGINAL
            # clipboard, never the intervening transcription T1.
            scheduled[1]()
            assert fake_clip.text() == 'ORIGINAL'


def test_clipboard_restore_preserves_non_text_formats():
    """A non-text clipboard payload (e.g. an image) must survive the
    snapshot -> paste -> restore cycle intact."""
    with _FakePynputSetup():
        import input_simulation
        fake_clip = FakeClipboard()
        fake_clip.set_mime({'image/png': b'PNGDATA', 'text/plain': b'caption'})
        fake_kb = FakeKeyboard()
        sim = make_simulator(fake_kb)

        scheduled = []
        with patch.object(input_simulation.ConfigManager, 'get_config_value',
                          return_value='clipboard'), \
             patch.object(input_simulation, '_get_clipboard', return_value=fake_clip), \
             patch.object(input_simulation, '_process_qt_events'), \
             patch.object(input_simulation, '_single_shot',
                          side_effect=lambda d, cb: scheduled.append(cb)), \
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('transcripcion')

            # The transcription replaced the image while the paste happens.
            assert fake_clip.text() == 'transcripcion'

            # Deferred restore fires: the original image + caption come back.
            scheduled[0]()

        restored = fake_clip.mimeData()
        assert 'image/png' in restored.formats()
        assert bytes(restored.data('image/png')) == b'PNGDATA'
        assert restored.text() == 'caption'
