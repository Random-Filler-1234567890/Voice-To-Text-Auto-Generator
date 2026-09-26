"""py2app build script - produces a real double-clickable VoiceFlow.app.

Run via ``build_macos_app.sh``, or directly on macOS with:
    python setup.py py2app
"""

import os

from setuptools import setup

APP = ["voiceflow/main.py"]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "VoiceFlow",
        "CFBundleDisplayName": "VoiceFlow",
        "CFBundleIdentifier": "com.voiceflow.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": False,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": (
            "VoiceFlow needs microphone access to transcribe your dictation."
        ),
    },
    "packages": [
        "rumps",
        "pynput",
        "sounddevice",
        "numpy",
        "requests",
        "pyperclip",
        "voiceflow",
    ],
}

if os.path.exists("assets/icon.icns"):
    OPTIONS["iconfile"] = "assets/icon.icns"

setup(
    app=APP,
    name="VoiceFlow",
    version="1.0.0",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
