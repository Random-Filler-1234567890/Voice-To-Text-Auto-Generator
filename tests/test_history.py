import json

from voiceflow.history import DictationHistory


def test_creates_empty_history_on_first_run(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json")
    assert history.count() == 0
    assert history.recent() == []


def test_record_adds_newest_first(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json")
    history.record("first dictation", app_name="Slack")
    history.record("second dictation", app_name="VS Code")
    recent = history.recent()
    assert recent[0].text == "second dictation"
    assert recent[1].text == "first dictation"


def test_word_count_computed_automatically(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json")
    entry = history.record("this has five words here", app_name="")
    assert entry.word_count == 5


def test_capped_at_max_entries(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json", max_entries=3)
    for i in range(5):
        history.record(f"dictation {i}")
    assert history.count() == 3
    # Newest entries survive, oldest are dropped.
    texts = [e.text for e in history.recent(10)]
    assert texts == ["dictation 4", "dictation 3", "dictation 2"]


def test_persists_to_disk(tmp_path):
    path = tmp_path / "history.json"
    history = DictationHistory(path=path)
    history.record("persisted text", app_name="Notes")
    on_disk = json.loads(path.read_text())
    assert on_disk["entries"][0]["text"] == "persisted text"


def test_clear_empties_history(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json")
    history.record("something")
    history.clear()
    assert history.count() == 0


def test_recent_respects_limit(tmp_path):
    history = DictationHistory(path=tmp_path / "history.json")
    for i in range(5):
        history.record(f"dictation {i}")
    assert len(history.recent(2)) == 2


def test_corrupt_history_file_recovers(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not valid json")
    history = DictationHistory(path=path)
    assert history.count() == 0
    assert path.with_suffix(".json.bak").exists()
