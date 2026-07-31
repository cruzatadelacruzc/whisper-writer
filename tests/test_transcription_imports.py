"""import transcription must stay cheap: the heavy libraries are deferred
into the functions that use them (spec: async-model-load). A module-level
reimport of faster_whisper/openai would put ~40s back on the startup path,
so this is checked in a CLEAN subprocess interpreter, not in-process."""
import os
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

CHECK = (
    "import sys, os;"
    "sys.path.insert(0, os.path.join(%r, 'src'));"
    "import transcription;"
    "assert 'faster_whisper' not in sys.modules, 'faster_whisper imported at module level';"
    "assert 'openai' not in sys.modules, 'openai imported at module level';"
    "print('DEFERRED_OK')"
) % (PROJECT_ROOT,)


def test_importing_transcription_does_not_pull_heavy_libraries():
    result = subprocess.run(
        [sys.executable, '-c', CHECK],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert 'DEFERRED_OK' in result.stdout
