import json

from voiceflow.config import ConfigManager, DEFAULT_CONFIG


def test_creates_default_config_on_first_run(tmp_config_path):
    cm = ConfigManager(path=tmp_config_path)
    assert tmp_config_path.exists()
    assert cm.get("hotkey.key") == "alt_r"
    assert cm.get("providers.transcription_order") == ["groq", "openai", "local"]


def test_get_set_dotted_path(tmp_config_path):
    cm = ConfigManager(path=tmp_config_path)
    cm.set("providers.groq_api_key", "sk-test-123")
    assert cm.get("providers.groq_api_key") == "sk-test-123"

    # Persisted to disk immediately.
    on_disk = json.loads(tmp_config_path.read_text())
    assert on_disk["providers"]["groq_api_key"] == "sk-test-123"


def test_missing_key_returns_default(tmp_config_path):
    cm = ConfigManager(path=tmp_config_path)
    assert cm.get("nonexistent.key", "fallback") == "fallback"
    assert cm.get("nonexistent.key") is None


def test_forward_compatible_merge_adds_new_keys(tmp_config_path):
    # Simulate an older on-disk config missing a key that a newer
    # DEFAULT_CONFIG introduced.
    old_config = json.loads(json.dumps(DEFAULT_CONFIG))
    del old_config["ui"]["sound_feedback"]
    tmp_config_path.write_text(json.dumps(old_config))

    cm = ConfigManager(path=tmp_config_path)
    assert cm.get("ui.sound_feedback") is True  # backfilled from defaults


def test_corrupt_config_recovers_with_backup(tmp_config_path):
    tmp_config_path.write_text("{not valid json")
    cm = ConfigManager(path=tmp_config_path)
    assert cm.get("hotkey.key") == "alt_r"
    backup_path = tmp_config_path.with_suffix(".json.bak")
    assert backup_path.exists()


def test_configured_providers_filters_missing_keys(tmp_config_path):
    cm = ConfigManager(path=tmp_config_path)
    cm.update(
        {
            "providers.groq_api_key": "key1",
            "providers.openai_api_key": "",
            "providers.transcription_order": ["groq", "openai", "local"],
        }
    )
    assert cm.configured_providers("providers.transcription_order") == ["groq", "local"]


def test_update_batches_a_single_save(tmp_config_path, monkeypatch):
    cm = ConfigManager(path=tmp_config_path)
    save_calls = []
    original_save = cm._save_locked

    def counting_save():
        save_calls.append(1)
        original_save()

    monkeypatch.setattr(cm, "_save_locked", counting_save)
    cm.update({"hotkey.key": "cmd_r", "hotkey.mode": "toggle"})
    assert len(save_calls) == 1
    assert cm.get("hotkey.key") == "cmd_r"
    assert cm.get("hotkey.mode") == "toggle"


def test_has_any_provider_configured(tmp_config_path):
    cm = ConfigManager(path=tmp_config_path)
    assert cm.has_any_provider_configured() is False
    cm.set("providers.anthropic_api_key", "sk-ant-1")
    assert cm.has_any_provider_configured() is True
