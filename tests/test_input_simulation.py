import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


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


def make_simulator(fake_keyboard):
    """Build an InputSimulator configured for the clipboard method."""
    import input_simulation
    with patch.object(input_simulation.ConfigManager, 'get_config_value',
                      side_effect=lambda section, key: {
                          'input_method': 'clipboard',
                          'writing_key_press_delay': 0,
                      }[key]):
        sim = input_simulation.InputSimulator()
    sim.keyboard = fake_keyboard
    return sim


def test_clipboard_paste_sets_text_and_restores_previous():
    import input_simulation
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
    from pynput.keyboard import Key
    assert ('hold', Key.ctrl) in fake_kb.events
    assert ('press', 'v') in fake_kb.events


def test_clipboard_failure_falls_back_to_typing():
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
