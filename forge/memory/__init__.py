"""
forge.memory — Archival and recall memory backed by SQLite.

Public exports:
    MemoryStore  — the SQLite-backed storage engine

Side-effect note:
    Import ``forge.memory.tools`` to register memory_search, memory_insert,
    and memory_evict into the shared tool registry (done automatically by
    ``forge.tools.__init__``).
"""
from forge.memory.store import MemoryStore

__all__ = ["MemoryStore"]
