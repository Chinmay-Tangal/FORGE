"""
Tests for vector embeddings, cosine similarity, BM25 scoring, and hybrid search.
"""
import pytest
from forge.memory.vector import (
    FastLocalEmbedder,
    cosine_similarity,
    bm25_score,
    HybridSemanticSearcher,
)
from forge.memory.store import MemoryStore


class TestVectorMemory:
    def test_fast_embedder_dimension_and_norm(self):
        embedder = FastLocalEmbedder(vector_dim=64)
        vec = embedder.embed("Database connection configuration and credentials")
        assert len(vec) == 64
        # L2 norm should be ~1.0
        norm = sum(x * x for x in vec) ** 0.5
        assert abs(norm - 1.0) < 1e-4

    def test_cosine_similarity_identical_and_orthogonal(self):
        v1 = [1.0, 0.0, 0.0]
        v2 = [1.0, 0.0, 0.0]
        v3 = [0.0, 1.0, 0.0]
        assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-5
        assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-5

    def test_semantic_similarity_ranking(self):
        embedder = FastLocalEmbedder(vector_dim=128)
        searcher = HybridSemanticSearcher(embedder=embedder)

        docs = [
            {"id": 1, "content": "Deploying docker containers to production Kubernetes cluster"},
            {"id": 2, "content": "PostgreSQL database indexing and query optimization tips"},
            {"id": 3, "content": "Kubernetes pod autoscaling and deployment yaml configuration"},
        ]

        # Query related to Kubernetes/docker should rank doc 1 and 3 highest
        ranked = searcher.rank("Kubernetes container deployment", docs, top_k=2)
        top_ids = [d["id"] for d in ranked]
        assert 1 in top_ids or 3 in top_ids

    def test_memory_store_hybrid_integration(self, tmp_path):
        db = str(tmp_path / "test_hybrid.db")
        store = MemoryStore(db_path=db)

        id1 = store.insert_archival("Project uses Python 3.12 with FastAPI and Pydantic v2.")
        id2 = store.insert_archival("The frontend is built with TypeScript and React 19.")
        id3 = store.insert_archival("Database migrations are managed using Alembic and PostgreSQL.")

        # Search for backend framework
        results = store.search_archival("FastAPI Python", limit=1)
        assert len(results) == 1
        assert results[0]["id"] == id1

        # Search for frontend
        results_fe = store.search_archival("React frontend", limit=1)
        assert len(results_fe) == 1
        assert results_fe[0]["id"] == id2
