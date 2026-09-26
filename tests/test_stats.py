from voiceflow.stats import UsageStats


def test_starts_at_zero(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    assert stats.total_dictations == 0
    assert stats.total_words == 0
    assert stats.total_facts_learned == 0
    assert stats.estimated_minutes_saved == 0.0


def test_record_dictation_accumulates(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    stats.record_dictation(10)
    stats.record_dictation(20)
    assert stats.total_dictations == 2
    assert stats.total_words == 30


def test_record_fact_learned(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    stats.record_fact_learned()
    stats.record_fact_learned()
    assert stats.total_facts_learned == 2


def test_record_meeting_adds_to_total_words(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    stats.record_dictation(10)
    stats.record_meeting(500)
    assert stats.total_words == 510


def test_estimated_minutes_saved_grows_with_words(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    stats.record_dictation(4000)
    # 4000 words: 4000/40=100min typing, 4000/150=26.7min speaking -> ~73min saved
    assert stats.estimated_minutes_saved > 70
    assert stats.estimated_minutes_saved < 76


def test_persists_across_instances(tmp_path):
    path = tmp_path / "stats.json"
    stats1 = UsageStats(path=path)
    stats1.record_dictation(50)
    stats2 = UsageStats(path=path)
    assert stats2.total_words == 50


def test_summary_line_no_dictations(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    assert stats.summary_line() == "No dictations yet"


def test_summary_line_with_words(tmp_path):
    stats = UsageStats(path=tmp_path / "stats.json")
    stats.record_dictation(2000)
    line = stats.summary_line()
    assert "2,000 words dictated" in line
    assert "saved" in line


def test_corrupt_stats_file_recovers(tmp_path):
    path = tmp_path / "stats.json"
    path.write_text("{not valid json")
    stats = UsageStats(path=path)
    assert stats.total_words == 0
    assert path.with_suffix(".json.bak").exists()
