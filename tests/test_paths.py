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
