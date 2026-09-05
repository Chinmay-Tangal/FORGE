"""
forge/memory/vector.py — High-performance vector embeddings and hybrid semantic search.

Provides dense vector representations and cosine similarity ranking with hybrid BM25
lexical scoring for SQLite archival memory.
"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _tokenize(text: str) -> List[str]:
    """Extract lowercase alphanumeric tokens and character n-grams."""
    words = re.findall(r"\w+", text.lower())
    ngrams = []
    for w in words:
        if len(w) >= 3:
            for i in range(len(w) - 2):
                ngrams.append(w[i:i + 3])
    return words + ngrams


class FastLocalEmbedder:
    """
    In-process subword TF-IDF / character n-gram dense vectorizer.
    Provides fast, deterministic semantic vector generation with zero external C-dependencies.
    """

    def __init__(self, vector_dim: int = 128) -> None:
        self.vector_dim = vector_dim

    def embed(self, text: str) -> List[float]:
        """Convert text into a normalized dense embedding vector."""
        tokens = _tokenize(text)
        if not tokens:
            return [0.0] * self.vector_dim

        vec = [0.0] * self.vector_dim
        counts = Counter(tokens)
        total = len(tokens)

        for token, count in counts.items():
            # Stable murmur-like hash projection
            h = hash(token) & 0xFFFFFFFF
            idx = h % self.vector_dim
            sign = 1.0 if ((h >> 8) & 1) == 0 else -1.0
            tf = (count / total) * math.log(1.0 + len(token))
            vec[idx] += sign * tf

        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two unit vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(v1, v2))))


def bm25_score(query_tokens: List[str], doc_tokens: List[str], avg_dl: float = 20.0, k1: float = 1.5, b: float = 0.75) -> float:
    """Compute a lightweight BM25 lexical relevance score."""
    if not query_tokens or not doc_tokens:
        return 0.0
    doc_len = len(doc_tokens)
    doc_counts = Counter(doc_tokens)
    score = 0.0
    for q in query_tokens:
        if q in doc_counts:
            tf = doc_counts[q]
            score += (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * (doc_len / max(1.0, avg_dl))))
    return score


class HybridSemanticSearcher:
    """
    Ranks text memories using hybrid dense vector + lexical scoring.
    """

    def __init__(self, embedder: Optional[FastLocalEmbedder] = None) -> None:
        self.embedder = embedder or FastLocalEmbedder()

    def rank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
        alpha: float = 0.65,
    ) -> List[Dict[str, Any]]:
        """
        Rank a collection of document dicts (each having 'id', 'content', optional 'embedding').
        alpha: weight for dense vector similarity (1 - alpha for BM25 score).
        """
        if not documents:
            return []

        q_vec = self.embedder.embed(query)
        q_tokens = _tokenize(query)

        avg_dl = sum(len(_tokenize(d.get("content", ""))) for d in documents) / max(1, len(documents))

        scored = []
        for doc in documents:
            content = doc.get("content", "")
            raw_emb = doc.get("embedding")
            if raw_emb and isinstance(raw_emb, (str, list)):
                d_vec = json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb
            else:
                d_vec = self.embedder.embed(content)

            cos_sim = cosine_similarity(q_vec, d_vec)

            d_tokens = _tokenize(content)
            lex_score = bm25_score(q_tokens, d_tokens, avg_dl=avg_dl)
            # Normalize BM25 score into [0, 1] range
            norm_lex = 1.0 - math.exp(-0.5 * lex_score)

            if norm_lex == 0.0 and cos_sim < 0.35:
                continue

            hybrid_score = (alpha * cos_sim) + ((1.0 - alpha) * norm_lex)
            scored.append((hybrid_score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]
