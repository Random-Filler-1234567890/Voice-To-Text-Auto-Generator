"""Lightweight, dependency-free relevance ranking for the memory store.

Rather than pulling in a heavyweight embedding model / vector DB (which
would blow up install size and cold-start latency for what is, in
practice, a corpus of a few hundred to a couple thousand short text
snippets), this implements classic TF-IDF cosine similarity by hand in
pure Python + math. It is fully deterministic, has zero network calls,
and is fast enough to recompute per-query (milliseconds for thousands of
entries) - correctness and testability over premature "vector store"
infrastructure.

A small recency/use-count boost is layered on top so facts the user
relies on often (and taught recently) edge out stale, rarely-relevant
ones when scores are close.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

_TOKEN_RE = re.compile(r"[a-z0-9']+")

_STOPWORDS = frozenset(
    """
    a an the of to in on at for and or but is are was were be been being
    this that these those it its i you he she they we my your his her
    their our me him them us with as by from into about over under
    again further then once here there when where why how all any both
    each few more most other some such no nor not only own same so than
    too very s t can will just don should now
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class ScoredItem:
    item_id: str
    score: float


class RelevanceRanker:
    """Ranks a corpus of ``(id, text)`` pairs against a query string."""

    def __init__(self, recency_half_life_days: float = 30.0, recency_weight: float = 0.15):
        self._recency_half_life_days = recency_half_life_days
        self._recency_weight = recency_weight

    def rank(
        self,
        query: str,
        corpus: Sequence[tuple[str, str]],
        timestamps: dict[str, float] | None = None,
        top_k: int = 8,
        min_score: float = 0.05,
    ) -> list[ScoredItem]:
        """Return the ``top_k`` best-matching corpus entries for ``query``.

        ``corpus`` is a sequence of ``(item_id, text)``. ``timestamps`` is
        an optional ``{item_id: unix_epoch_seconds}`` map used for the
        recency boost; entries missing from it get no boost.
        """
        if not corpus:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        doc_tokens: dict[str, list[str]] = {item_id: tokenize(text) for item_id, text in corpus}

        # Document frequency across the corpus, for IDF.
        df: Counter[str] = Counter()
        for tokens in doc_tokens.values():
            for term in set(tokens):
                df[term] += 1
        n_docs = len(doc_tokens)

        def idf(term: str) -> float:
            return math.log((1 + n_docs) / (1 + df.get(term, 0))) + 1.0

        query_vec = self._tfidf_vector(query_tokens, idf)
        query_norm = self._norm(query_vec)
        if query_norm == 0:
            return []

        now = time.time()
        scored: list[ScoredItem] = []
        for item_id, tokens in doc_tokens.items():
            if not tokens:
                continue
            doc_vec = self._tfidf_vector(tokens, idf)
            doc_norm = self._norm(doc_vec)
            if doc_norm == 0:
                continue
            dot = sum(query_vec.get(term, 0.0) * weight for term, weight in doc_vec.items())
            cosine = dot / (query_norm * doc_norm)

            boost = 0.0
            if timestamps and item_id in timestamps:
                age_days = max(0.0, (now - timestamps[item_id]) / 86400.0)
                recency = 0.5 ** (age_days / self._recency_half_life_days)
                boost = self._recency_weight * recency

            final_score = cosine * (1.0 - self._recency_weight) + boost
            if final_score >= min_score:
                scored.append(ScoredItem(item_id=item_id, score=final_score))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _tfidf_vector(tokens: list[str], idf_fn) -> dict[str, float]:
        counts = Counter(tokens)
        max_count = max(counts.values())
        vec = {}
        for term, count in counts.items():
            tf = 0.5 + 0.5 * (count / max_count)  # augmented term frequency
            vec[term] = tf * idf_fn(term)
        return vec

    @staticmethod
    def _norm(vec: dict[str, float]) -> float:
        return math.sqrt(sum(v * v for v in vec.values()))
