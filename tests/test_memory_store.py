import json

import pytest

from voiceflow.memory.store import MemoryStore


def test_creates_empty_store_on_first_run(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    assert tmp_memory_path.exists()
    assert store.count() == 0


def test_add_entry_persists_to_disk(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    entry = store.add_entry("person", "Sarah Chen is my boss")
    assert store.count() == 1

    on_disk = json.loads(tmp_memory_path.read_text())
    assert on_disk["entries"][0]["id"] == entry.id
    assert on_disk["entries"][0]["text"] == "Sarah Chen is my boss"


def test_add_entry_rejects_empty_text(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    with pytest.raises(ValueError):
        store.add_entry("fact", "   ")


def test_unknown_category_falls_back_to_fact(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    entry = store.add_entry("nonsense_category", "some fact")
    assert entry.category == "fact"


def test_learn_from_facts_skips_malformed_entries(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    facts = [
        {"category": "person", "text": "Sarah is my boss"},
        {"category": "vocabulary"},  # missing 'text' - should be skipped
        {"text": "an acronym fact"},  # missing category - defaults to fact
    ]
    added = store.learn_from_facts(facts)
    assert len(added) == 2
    assert store.count() == 2


def test_delete_entry(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    entry = store.add_entry("fact", "test fact")
    assert store.delete_entry(entry.id) is True
    assert store.count() == 0
    assert store.delete_entry("nonexistent-id") is False


def test_update_entry(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    entry = store.add_entry("fact", "original text")
    assert store.update_entry(entry.id, "updated text") is True
    assert store.all_entries()[0].text == "updated text"


def test_relevant_snippets_returns_matching_text(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    store.add_entry("person", "Sarah Chen is my boss at Acme Corp")
    store.add_entry("preference", "I prefer coffee over tea")
    snippets = store.relevant_snippets("send an email to sarah about the acme deal")
    assert any("Sarah Chen" in s for s in snippets)


def test_relevant_snippets_marks_use_count(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    entry = store.add_entry("person", "Sarah Chen is my boss at Acme Corp")
    assert entry.use_count == 0
    store.relevant_snippets("email sarah at acme")
    reloaded = store.all_entries()[0]
    assert reloaded.use_count == 1
    assert reloaded.last_used_at is not None


def test_capacity_eviction(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path, max_entries=3)
    for i in range(5):
        store.add_entry("fact", f"fact number {i}")
    assert store.count() == 3


def test_corrupt_memory_file_recovers(tmp_memory_path):
    tmp_memory_path.write_text("{not valid json")
    store = MemoryStore(path=tmp_memory_path)
    assert store.count() == 0
    assert tmp_memory_path.with_suffix(".json.bak").exists()


def test_entries_by_category(tmp_memory_path):
    store = MemoryStore(path=tmp_memory_path)
    store.add_entry("person", "Sarah is my boss")
    store.add_entry("acronym", "API means Application Programming Interface")
    store.add_entry("person", "Tom is my coworker")
    people = store.entries_by_category("person")
    assert len(people) == 2
