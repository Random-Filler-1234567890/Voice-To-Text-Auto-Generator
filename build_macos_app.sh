#!/usr/bin/env bash
# One-time build script: run this in Terminal on your Mac ONCE to produce a
# real, double-clickable VoiceFlow.app. After this, you never need Terminal
# again - just keep VoiceFlow.app in /Applications and open it like any
# other app.
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
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

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

echo ""
echo "================================================================"
echo " Build complete: dist/VoiceFlow.app"
echo ""
echo " Next steps:"
echo "   1. Drag dist/VoiceFlow.app into /Applications"
echo "      (or run: cp -R dist/VoiceFlow.app /Applications/)"
echo "   2. Open it from Applications or Spotlight (Cmd+Space, 'VoiceFlow')"
echo "   3. macOS will ask for Microphone, Accessibility, and Input"
echo "      Monitoring permissions the first time - approve all three,"
echo "      then quit and reopen VoiceFlow once."
echo "   4. Click the mic icon in your menu bar -> AI Providers -> add a"
echo "      Groq (or OpenAI/Anthropic) API key."
echo "   5. Hold Right Option and speak anywhere. Release to paste."
echo ""
echo " If macOS says the app 'cannot be opened because it is from an"
echo " unidentified developer' (expected for an unsigned personal build):"
echo "   Right-click VoiceFlow.app -> Open -> Open (only needed once)."
echo "================================================================"
