from pathlib import Path

from voiceflow import paths


def test_default_meeting_notes_dir_lives_under_app_support(monkeypatch):
    monkeypatch.delenv("VOICEFLOW_MEETING_NOTES_DIR", raising=False)
    result = paths._default_meeting_notes_dir()
    assert result == paths.APP_SUPPORT_DIR / "Meeting Notes"


def test_default_meeting_notes_dir_is_not_under_documents(monkeypatch):
    # Regression test: writing to ~/Documents requires a separate,
    # undeclared macOS "Documents folder" permission VoiceFlow never
    # requests, which silently breaks Meeting Notes with a PermissionError.
    monkeypatch.delenv("VOICEFLOW_MEETING_NOTES_DIR", raising=False)
    result = paths._default_meeting_notes_dir()
    assert "Documents" not in result.parts


def test_meeting_notes_dir_override_respected(monkeypatch, tmp_path):
    override = tmp_path / "custom-notes-location"
    monkeypatch.setenv("VOICEFLOW_MEETING_NOTES_DIR", str(override))
    result = paths._default_meeting_notes_dir()
    assert result == override


def test_ensure_meeting_notes_dir_creates_it(tmp_path, monkeypatch):
    target = tmp_path / "notes"
    monkeypatch.setattr(paths, "MEETING_NOTES_DIR", target)
    assert not target.exists()
    paths.ensure_meeting_notes_dir()
    assert target.is_dir()


def _make_fake_checkout(base: Path) -> Path:
    checkout = base / "checkout"
    checkout.mkdir(parents=True)
    (checkout / "update_macos_app.sh").write_text("#!/usr/bin/env bash\n")
    return checkout


def test_find_source_dir_uses_sentinel_file(tmp_path):
    app_support = tmp_path / "app_support"
    app_support.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    checkout = _make_fake_checkout(tmp_path / "custom-location")
    (app_support / paths.SOURCE_DIR_SENTINEL_NAME).write_text(str(checkout))

    result = paths.find_source_dir(app_support, home)
    assert result == checkout


def test_find_source_dir_falls_back_to_home_voiceflow(tmp_path):
    app_support = tmp_path / "app_support"
    app_support.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    checkout = home / "VoiceFlow"
    checkout.mkdir()
    (checkout / "update_macos_app.sh").write_text("#!/usr/bin/env bash\n")

    result = paths.find_source_dir(app_support, home)
    assert result == checkout


def test_find_source_dir_ignores_stale_sentinel_pointing_nowhere(tmp_path):
    app_support = tmp_path / "app_support"
    app_support.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    (app_support / paths.SOURCE_DIR_SENTINEL_NAME).write_text(str(tmp_path / "does-not-exist"))

    # No fallback ~/VoiceFlow either - should give up cleanly, not raise.
    result = paths.find_source_dir(app_support, home)
    assert result is None


def test_find_source_dir_returns_none_when_nothing_found(tmp_path):
    app_support = tmp_path / "app_support"
    app_support.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    result = paths.find_source_dir(app_support, home)
    assert result is None


def test_find_source_dir_requires_update_script_present(tmp_path):
    # A folder existing at the sentinel path isn't enough - it must
    # actually contain update_macos_app.sh, or it's not a valid checkout.
    app_support = tmp_path / "app_support"
    app_support.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    (app_support / paths.SOURCE_DIR_SENTINEL_NAME).write_text(str(empty_dir))

    result = paths.find_source_dir(app_support, home)
    assert result is None
