#!/usr/bin/env bash
# Run this whenever you want to pull the latest VoiceFlow changes from
# GitHub and rebuild/reinstall the app in one step. This is the answer to
# "do I have to update it through GitHub" - yes, but this script is the
# entire process: one command, then VoiceFlow reopens itself, updated.
#
# This only ever reports success if build_macos_app.sh's own self-test
# (import check + a real launch-and-stay-running check) actually passed -
# see that script for details. If anything failed, this script stops and
# tells you so instead of printing "Done!" over a broken install.
#
# Usage:
#   ./update_macos_app.sh
#
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script updates the macOS .app bundle and must be run on a Mac." >&2
    exit 1
fi

cd "$(dirname "$0")"

echo "==> Pulling the latest changes from GitHub..."
git pull

echo "==> Quitting any running VoiceFlow..."
osascript -e 'tell application "VoiceFlow" to quit' 2>/dev/null || true
sleep 1
killall VoiceFlow >/dev/null 2>&1 || true
sleep 1

echo "==> Rebuilding (this also verifies the build actually works)..."
./build_macos_app.sh
# build_macos_app.sh exits non-zero (and set -e above stops this script)
# if either its import check or its launch check failed, so reaching the
# line below means the freshly-built dist/VoiceFlow.app is confirmed
# working - it's currently running from its smoke test.

echo "==> Installing the verified build to /Applications..."
killall VoiceFlow >/dev/null 2>&1 || true
sleep 1
rm -rf "/Applications/VoiceFlow.app"
cp -R dist/VoiceFlow.app /Applications/

echo "==> Reopening VoiceFlow from /Applications..."
open /Applications/VoiceFlow.app
sleep 2
if pgrep -x "VoiceFlow" >/dev/null 2>&1; then
    echo ""
    echo "Done! VoiceFlow has been updated and relaunched from /Applications."
else
    echo ""
    echo "WARNING: the verified build ran fine during its self-test, but the"
    echo "copy in /Applications isn't staying running. This would be unusual -"
    echo "try opening /Applications/VoiceFlow.app manually and, if it still"
    echo "does nothing, run ./run_dev.sh and send me exactly what it prints."
    exit 1
fi
