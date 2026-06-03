#!/usr/bin/env bash
set -euo pipefail

WAVE="${1:-}"

if [[ -z "$WAVE" ]]; then
    echo "Usage: sim/view_waveform.sh path/to/waveform.vcd" >&2
    echo "       make -C sim view-wave WAVE=path/to/waveform.vcd" >&2
    exit 2
fi

if [[ ! -f "$WAVE" ]]; then
    echo "Waveform not found: $WAVE" >&2
    exit 1
fi

if ! command -v gtkwave >/dev/null 2>&1; then
    echo "gtkwave was not found on PATH. Install GTKWave, then open: $WAVE" >&2
    exit 1
fi

exec gtkwave "$WAVE"
