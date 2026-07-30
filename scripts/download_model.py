"""Resumable download of a Whisper model for faster-whisper.

Usage (from the project root):
    venv/bin/python scripts/download_model.py [model]

Downloads "medium" when no argument is given. If the download is interrupted
(power outage, network drop, Ctrl+C), just run the same command again: it
resumes where it left off, and finishes instantly if already complete.

For unattended downloads on unstable connections prefer the watchdog wrapper,
which also restarts stalled transfers automatically:
    bash scripts/download_model.sh [model]

The model lands in the HuggingFace cache (~/.cache/huggingface), which is
where faster-whisper looks for it — the app will not download it again.
"""
import os
import sys

# The xet transfer backend stalls indefinitely on slow/unstable connections
# (observed 2026-07); the classic HTTP path resumes reliably via Range requests.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from huggingface_hub import snapshot_download

model = sys.argv[1] if len(sys.argv) > 1 else "medium"
repo = f"Systran/faster-whisper-{model}"

print(f"Downloading {repo} (resumable, re-run if interrupted)...")
path = snapshot_download(repo)

# When the network is unreachable, snapshot_download falls back to the local
# cache and can return an incomplete snapshot as if it succeeded — verify the
# weights file is really there before declaring success.
if not os.path.exists(os.path.join(path, "model.bin")):
    sys.exit(f"model.bin is missing from {path} — download incomplete "
             "(network down?). Re-run to resume.")
print(f"Model '{model}' complete at: {path}")
