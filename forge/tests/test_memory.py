"""
tests/test_memory.py — Tests for forge.memory.store.MemoryStore.
"""
from __future__ import annotations

import pytest

from forge.memory.store import MemoryStore


@pytest.fixture
def mem(tmp_path):
    return MemoryStore(db_path=str(tmp_path / "test.db"))


class TestArchivalMemory:
    def test_insert_and_search(self, mem):
        mem_id = mem.insert_archival("The capital of France is Paris.")
        assert isinstance(mem_id, int)
        results = mem.search_archival("France")
        assert len(results) == 1
        assert "Paris" in results[0]["content"]

    def test_search_no_match(self, mem):
        mem.insert_archival("Nothing relevant here.")
        results = mem.search_archival("zebra")
        assert results == []

    def test_evict(self, mem):
        mem_id = mem.insert_archival("Temporary fact.")
        ok = mem.evict_archival(mem_id)
        assert ok is True
        results = mem.search_archival("Temporary")
        assert results == []

    def test_evict_nonexistent(self, mem):
        ok = mem.evict_archival(9999)
        assert ok is False

    def test_search_limit(self, mem):
        for i in range(10):
            mem.insert_archival(f"fact number {i}")
        results = mem.search_archival("fact", limit=3)
        assert len(results) <= 3


class TestRecallMemory:
    def test_insert_and_retrieve(self, mem):
        mem.insert_recall("evt-001", "Message", {"role": "user", "content": "hi"})
        history = mem.get_recall_history(limit=10)
        assert len(history) == 1
        assert history[0]["event_type"] == "Message"

    def test_history_limit(self, mem):
        for i in range(20):
            mem.insert_recall(f"evt-{i:03d}", "Message", {"content": str(i)})
        history = mem.get_recall_history(limit=5)
        assert len(history) == 5
