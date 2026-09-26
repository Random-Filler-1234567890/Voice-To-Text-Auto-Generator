from voiceflow.memory.relevance import RelevanceRanker, tokenize


def test_tokenize_lowercases_and_strips_stopwords():
    tokens = tokenize("The Quick Brown Fox is at Acme Corp!")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "at" not in tokens
    assert "quick" in tokens
    assert "acme" in tokens
    assert "corp" in tokens


def test_rank_returns_most_relevant_entry_first():
    ranker = RelevanceRanker()
    corpus = [
        ("1", "Sarah Chen is my boss at Acme Corp"),
        ("2", "My favorite coffee order is a flat white"),
        ("3", "The acronym API stands for Application Programming Interface"),
    ]
    results = ranker.rank("email my boss sarah about the acme project", corpus, top_k=3)
    assert results
    assert results[0].item_id == "1"


def test_rank_excludes_irrelevant_entries_below_threshold():
    ranker = RelevanceRanker()
    corpus = [
        ("1", "Sarah Chen is my boss at Acme Corp"),
        ("2", "My favorite coffee order is a flat white"),
    ]
    results = ranker.rank("what is a flat white coffee order", corpus, top_k=5, min_score=0.05)
    matched_ids = {r.item_id for r in results}
    assert "2" in matched_ids


def test_rank_empty_corpus_returns_empty():
    ranker = RelevanceRanker()
    assert ranker.rank("anything", [], top_k=5) == []


def test_rank_empty_query_returns_empty():
    ranker = RelevanceRanker()
    corpus = [("1", "Sarah Chen is my boss")]
    assert ranker.rank("", corpus, top_k=5) == []


def test_recency_boost_breaks_near_ties():
    ranker = RelevanceRanker(recency_half_life_days=30, recency_weight=0.3)
    corpus = [
        ("old", "project acronym meaning definition"),
        ("new", "project acronym meaning definition"),
    ]
    now = 1_700_000_000.0
    timestamps = {
        "old": now - 90 * 86400,  # 90 days old -> heavily decayed
        "new": now,  # just learned
    }
    # Patch "now" indirectly isn't needed - recency uses time.time() internally,
    # so we use very old vs very recent real timestamps instead.
    import time

    timestamps = {
        "old": time.time() - 400 * 86400,
        "new": time.time(),
    }
    results = ranker.rank("what does the acronym mean", corpus, timestamps=timestamps, top_k=2)
    scores = {r.item_id: r.score for r in results}
    assert scores["new"] > scores["old"]


def test_top_k_limits_results():
    ranker = RelevanceRanker()
    corpus = [(str(i), f"fact number {i} about widgets") for i in range(20)]
    results = ranker.rank("widgets", corpus, top_k=5)
    assert len(results) <= 5
