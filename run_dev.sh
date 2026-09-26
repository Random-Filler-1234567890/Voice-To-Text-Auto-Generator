#!/usr/bin/env bash
# Fast dev-mode loop: run VoiceFlow straight from source (no .app bundling)
# so you get full tracebacks in the terminal while testing changes.
# macOS only.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "VoiceFlow only runs on macOS." >&2
    exit 1
fi

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

python -m voiceflow.main
