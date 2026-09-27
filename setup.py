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
        # This is a menu-bar-only accessory app (like Bartender, or Wispr
        # Flow itself) - it must NOT be a regular foreground app.
        # LSUIElement=False was the actual root cause of "the app opens
        # but nothing happens": with it False, macOS makes VoiceFlow the
        # active application and puts its name in the standard menu bar
        # at the top-LEFT (next to the Apple logo) with an essentially
        # empty default menu - since rumps never populates that menu, only
        # its own status-bar dropdown at the top-RIGHT. Users reasonably
        # clicked the prominent bold app name at top-left, found nothing,
        # and never noticed the real, fully-working menu bar icon on the
        # right. LSUIElement=True removes the Dock icon and the top-left
        # presence entirely, leaving only the one, correct, working menu.
        "LSUIElement": True,
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
        # sounddevice's macOS wheel ships the actual PortAudio binary in a
        # SEPARATE top-level package, "_sounddevice_data" (not a submodule
        # of "sounddevice"). Without listing it here too, py2app doesn't
        # know it holds a native library and zips its contents - including
        # portaudio-binaries/libportaudio.dylib - into python39.zip. macOS
        # can't dlopen() a shared library from inside a zip file, so the
        # app builds and launches "fine" but every microphone access fails
        # with "cannot load library ... python39.zip/_sounddevice_data/...".
        # This one line is the actual fix for that bug.
        "_sounddevice_data",
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
