"""Startup-path imports must stay cheap: faster_whisper/openai are deferred
into the functions that use them (spec: async-model-load). A module-level
reimport in transcription.py OR in anything the GUI imports at startup
(model_load_thread, result_thread) would put ~40s back on the startup path,
so each module is checked in a CLEAN subprocess interpreter, not in-process."""
import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


@pytest.mark.parametrize('module', [
    'transcription',
    'model_load_thread',
    'result_thread',
])
def test_importing_module_does_not_pull_heavy_libraries(module):
    check = (
        "import sys, os;"
        "sys.path.insert(0, os.path.join(%r, 'src'));"
        "import %s;"
        "assert 'faster_whisper' not in sys.modules, 'faster_whisper imported at module level';"
        "assert 'openai' not in sys.modules, 'openai imported at module level';"
        "print('DEFERRED_OK')"
    ) % (PROJECT_ROOT, module)
    result = subprocess.run(
        [sys.executable, '-c', check],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert 'DEFERRED_OK' in result.stdout
