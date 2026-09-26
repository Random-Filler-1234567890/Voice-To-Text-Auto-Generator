#!/usr/bin/env bash
# Run this whenever you want to pull the latest VoiceFlow changes from
# GitHub and rebuild/reinstall the app in one step. This is the answer to
# "do I have to update it through GitHub" - yes, but this script is the
# entire process: one command, then VoiceFlow reopens itself, updated.
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

echo "==> Quitting VoiceFlow if it's running..."
osascript -e 'tell application "VoiceFlow" to quit' 2>/dev/null || true
sleep 1

echo "==> Rebuilding..."
./build_macos_app.sh

echo "==> Installing to /Applications..."
rm -rf "/Applications/VoiceFlow.app"
cp -R dist/VoiceFlow.app /Applications/

echo "==> Reopening VoiceFlow..."
open /Applications/VoiceFlow.app

echo ""
echo "Done! VoiceFlow has been updated and relaunched."
