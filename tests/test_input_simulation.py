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


class FakeClipboard:
    def __init__(self, initial='previous content'):
        self.history = [initial]

    def text(self):
        return self.history[-1]

    def setText(self, t):
        self.history.append(t)


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
             patch.object(input_simulation.time, 'sleep'):
            sim.typewrite('texto del informe')

        # The transcription was placed on the clipboard, then the previous
        # content was restored afterwards.
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
             patch.object(input_simulation.time, 'sleep'):
            # This should not raise; it should handle the failure gracefully.
            sim.typewrite('test text')

        # The text was placed on the clipboard and then restored.
        assert 'test text' in fake_clip.history
        assert fake_clip.text() == 'previous content'
        # No per-character typing occurred (no fallback after clipboard setup).
        assert ('press', 't') not in sim.keyboard.events
        assert ('press', 'e') not in sim.keyboard.events
