#!/usr/bin/env bash
# One-time build script: run this in Terminal on your Mac ONCE to produce a
# real, double-clickable VoiceFlow.app. After this, you never need Terminal
# again - just keep VoiceFlow.app in /Applications and open it like any
# other app.
#
# This script tests itself as it goes: it verifies the code actually
# imports cleanly BEFORE spending time packaging it, and it launches the
# finished .app for a few seconds afterward to confirm it starts up and
# stays running, rather than just declaring victory once the build
# commands exit with status 0.
#
# Usage:
#   chmod +x build_macos_app.sh
#   ./build_macos_app.sh
#
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script builds a macOS .app bundle and must be run on a Mac." >&2
    exit 1
fi

cd "$(dirname "$0")"

echo "==> Checking for Python 3..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 not found. Install it from https://www.python.org/downloads/ (or 'brew install python') and re-run this script." >&2
    exit 1
fi
python3 --version

echo "==> Creating virtual environment (.venv)..."
python3 -m venv .venv
source .venv/bin/activate

echo "==> Installing dependencies..."
echo "    (if this step fails, it's almost always a specific package's error"
echo "     message right above this line - read it before asking for help)"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "==> Verifying VoiceFlow imports cleanly before building..."
if ! python3 -c "
import sys
sys.path.insert(0, '.')
from voiceflow.app import VoiceFlowApp  # noqa: F401
print('    -> OK: voiceflow.app imports without error')
"; then
    echo ""
    echo "================================================================"
    echo " VoiceFlow failed to import - see the Python traceback above."
    echo " This is exactly the kind of problem that would otherwise make"
    echo " the built .app silently do nothing when you open it, so the"
    echo " build has been stopped here instead of continuing."
    echo "================================================================"
    exit 1
fi

echo "==> Building the app icon..."
if [[ -f assets/icon_1024.png ]]; then
    ICONSET_DIR="assets/icon.iconset"
    rm -rf "$ICONSET_DIR"
    mkdir -p "$ICONSET_DIR"
    for size in 16 32 64 128 256 512; do
        sips -z "$size" "$size" assets/icon_1024.png --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
        double=$((size * 2))
        sips -z "$double" "$double" assets/icon_1024.png --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET_DIR" -o assets/icon.icns
    rm -rf "$ICONSET_DIR"
    echo "    -> assets/icon.icns created"
else
    echo "    (assets/icon_1024.png missing - building without a custom icon)"
fi

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Building VoiceFlow.app with py2app..."
python setup.py py2app

APP_BINARY="dist/VoiceFlow.app/Contents/MacOS/VoiceFlow"
if [[ ! -x "$APP_BINARY" ]]; then
    echo "ERROR: py2app finished but the expected executable is missing at" >&2
    echo "  $APP_BINARY" >&2
    echo "The build did not produce a usable app - check the py2app output above." >&2
    exit 1
fi

echo "==> Smoke-testing the built app (launches it for a few seconds)..."
killall VoiceFlow >/dev/null 2>&1 || true
sleep 1
open "dist/VoiceFlow.app"
sleep 4
if pgrep -x "VoiceFlow" >/dev/null 2>&1; then
    SMOKE_TEST_OK=1
    echo "    -> VoiceFlow launched and is still running after 4 seconds. Good sign!"
else
    SMOKE_TEST_OK=0
fi

echo ""
echo "================================================================"
if [[ "$SMOKE_TEST_OK" == "1" ]]; then
    echo " Build complete and VoiceFlow is running: dist/VoiceFlow.app"
    echo ""
    echo " Next steps:"
    echo "   1. Move it into Applications so it stays put:"
    echo "      cp -R dist/VoiceFlow.app /Applications/ && killall VoiceFlow"
    echo "      open /Applications/VoiceFlow.app"
    echo "   2. macOS will ask for Microphone, Accessibility, and Input"
    echo "      Monitoring permissions the first time - approve all three,"
    echo "      then quit and reopen VoiceFlow once."
    echo "   3. Click the mic icon in your menu bar -> AI Providers ->"
    echo "      Quick Setup... to add a free API key."
    echo "   4. Hold Right Option and speak anywhere. Release to paste."
else
    echo " Build finished, but VoiceFlow did not stay running after launch."
    echo ""
    echo " This means it built successfully but is crashing or exiting on"
    echo " startup - exactly the 'nothing happens when I open it' problem,"
    echo " caught here instead of after you've already installed it."
    echo ""
    echo " To see the actual error, run this and read what it prints:"
    echo "   ./run_dev.sh"
    echo ""
    echo " Also check these two files for a saved error report:"
    echo "   ~/Library/Application Support/VoiceFlow/logs/crash.log"
    echo "   ~/Library/Application Support/VoiceFlow/logs/voiceflow.log"
fi
echo ""
echo " If macOS says the app 'cannot be opened because it is from an"
echo " unidentified developer' (expected for an unsigned personal build):"
echo "   Right-click VoiceFlow.app -> Open -> Open (only needed once)."
echo "================================================================"

if [[ "$SMOKE_TEST_OK" != "1" ]]; then
    # Non-zero exit so anything calling this script (update_macos_app.sh,
    # or you re-running it) can tell the build did NOT produce a working
    # app, instead of reporting "Done!" over a broken install.
    exit 1
fi
