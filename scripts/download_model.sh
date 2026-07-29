#!/usr/bin/env bash
# Unattended, stall-proof Whisper model download.
#
# Usage (from the project root):
#   bash scripts/download_model.sh [model]     # default: medium
#
# Wraps scripts/download_model.py with a watchdog: if the transfer makes no
# progress for 90 seconds it kills and relaunches it (resuming where it left
# off), and it retries after any crash. Safe to re-run at any time; exits as
# soon as the model is complete. Designed for unstable networks and power
# cuts: after an outage, just run it again.
set -u

MODEL="${1:-medium}"
CACHE_DIR="$HOME/.cache/huggingface/hub/models--Systran--faster-whisper-$MODEL"
PY="venv/bin/python"

while true; do
    "$PY" scripts/download_model.py "$MODEL" &
    PID=$!

    LAST_SIZE=-1
    while kill -0 "$PID" 2>/dev/null; do
        sleep 90
        SIZE=$(du -sk "$CACHE_DIR" 2>/dev/null | cut -f1)
        SIZE=${SIZE:-0}
        if [ "$SIZE" = "$LAST_SIZE" ] && kill -0 "$PID" 2>/dev/null; then
            echo "[watchdog] no progress in 90s (stuck at ${SIZE}KB); restarting download..."
            kill "$PID" 2>/dev/null
        fi
        LAST_SIZE=$SIZE
    done

    if wait "$PID"; then
        echo "[watchdog] download finished successfully."
        break
    fi
    echo "[watchdog] download exited without finishing; retrying in 15s..."
    sleep 15
done
