from __future__ import annotations

import math
import re
from collections import defaultdict


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _bm25_score(query: str, document: str, *, k1: float = 1.5, b: float = 0.75, avg_dl: float = 120.0) -> float:
    q_terms = _tokenize(query)
    if not q_terms:
        return 0.0
    d_terms = _tokenize(document)
    if not d_terms:
        return 0.0
    dl = len(d_terms)
    tf_map: dict[str, int] = defaultdict(int)
    for t in d_terms:
        tf_map[t] += 1
    score = 0.0
    for term in set(q_terms):
        tf = tf_map.get(term, 0)
        if tf == 0:
            continue
        idf = math.log(1 + 1)  # single-doc corpus approximation
        denom = tf + k1 * (1 - b + b * dl / avg_dl)
        score += idf * (tf * (k1 + 1)) / denom
    return score


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """RRF fusion across multiple ranked document-id lists."""
    scores: dict[str, float] = defaultdict(float)
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] += 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
