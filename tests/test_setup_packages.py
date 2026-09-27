"""Regression test for the py2app "native library trapped inside python39.zip"
bug: sounddevice's macOS wheel ships PortAudio's .dylib in a SEPARATE
top-level package, "_sounddevice_data", not inside "sounddevice" itself.
py2app only copies a package as a real unzipped directory (required for
dlopen() to work) when it's explicitly named in OPTIONS["packages"] - listing
"sounddevice" alone silently let "_sounddevice_data" get zipped into
python39.zip, breaking the microphone at runtime with an OSError.

This test doesn't run py2app (not installable/runnable off-macOS) - it just
asserts the fix (the extra packages entry) can never be quietly reverted.
"""

import ast
from pathlib import Path

SETUP_PY = Path(__file__).resolve().parent.parent / "setup.py"


def _load_py2app_packages() -> list[str]:
    tree = ast.parse(SETUP_PY.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "OPTIONS" for t in node.targets
        ):
            options = ast.literal_eval(node.value)
            return options["packages"]
    raise AssertionError("Could not find OPTIONS = {...} in setup.py")


def test_sounddevice_data_package_is_bundled_unzipped():
    packages = _load_py2app_packages()
    assert "sounddevice" in packages
    assert "_sounddevice_data" in packages, (
        "_sounddevice_data must be listed alongside sounddevice in "
        "setup.py's py2app OPTIONS['packages'], otherwise PortAudio's "
        "libportaudio.dylib gets zipped into python39.zip and every "
        "microphone access fails with an unloadable-library OSError."
    )


def test_numpy_still_bundled_unzipped():
    # numpy ships compiled .so extensions too - same failure mode applies.
    assert "numpy" in _load_py2app_packages()
