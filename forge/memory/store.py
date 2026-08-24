"""
forge/memory/store.py — SQLite-backed archival and recall memory.

Implements a two-tier MemGPT-style memory hierarchy:

  Archival memory  — long-term storage of facts and notes, searchable
                     by keyword (LIKE query). A vector-search upgrade
                     path is stubbed out in the schema (``embedding`` column).
  Recall memory    — raw event log for cross-session inspection.

Reference: MemGPT: Towards LLMs as Operating Systems (arXiv:2310.08560).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS archival_memory (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    content   TEXT    NOT NULL,
    timestamp TEXT    NOT NULL,
    embedding BLOB                    -- reserved for future vector search
);

CREATE TABLE IF NOT EXISTS recall_memory (
    id         TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    payload    TEXT NOT NULL
);
"""


class MemoryStore:
    """
    Persistent memory store backed by a local SQLite database.

    Parameters
    ----------
    db_path:
        Path to the SQLite file. The parent directory is created automatically.
    """

    def __init__(self, db_path: str = ".forge/memory.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(_SCHEMA)

    # Archival memory
    def insert_archival(self, content: str) -> int:
        """Persist a fact or note. Returns the new row ID."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO archival_memory (content, timestamp) VALUES (?, ?)",
                (content, datetime.utcnow().isoformat()),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def search_archival(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Keyword search over archival memory.

        This is a simple ``LIKE`` fallback. Replace with a vector-similarity
        query (sqlite-vec / chromadb) for semantic search.
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, content, timestamp FROM archival_memory "
                "WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit),
            )
            return [{"id": r[0], "content": r[1], "timestamp": r[2]} for r in cur.fetchall()]

    def evict_archival(self, mem_id: int) -> bool:
        """Delete a specific memory entry. Returns True if a row was deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM archival_memory WHERE id = ?", (mem_id,))
            return cur.rowcount > 0

    # Recall memory (raw event log)
    def insert_recall(self, event_id: str, event_type: str, payload: dict) -> None:
        """Append an event to the recall log."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO recall_memory (id, event_type, timestamp, payload) "
                "VALUES (?, ?, ?, ?)",
                (event_id, event_type, datetime.utcnow().isoformat(), json.dumps(payload)),
            )

    def get_recall_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent `limit` recall events, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT id, event_type, timestamp, payload "
                "FROM recall_memory ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "event_type": r[1], "timestamp": r[2], "payload": json.loads(r[3])}
            for r in reversed(rows)
        ]
