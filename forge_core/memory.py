import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class MemoryStore:
    """MemGPT-style OS memory hierarchy."""
    
    def __init__(self, db_path: str = ".forge/memory.db"):
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS archival_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    embedding BLOB
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS recall_memory (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            ''')
            conn.commit()

    def insert_archival(self, content: str) -> int:
        """Insert into long-term archival memory."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO archival_memory (content, timestamp) VALUES (?, ?)",
                (content, datetime.utcnow().isoformat())
            )
            return cursor.lastrowid
            
    def search_archival(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Semantic search over archival memory. (Placeholder for vector search)"""
        # In a full implementation, we'd embed the query and use sqlite-vec
        # For now, fallback to a simple LIKE query
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, content, timestamp FROM archival_memory WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                (f"%{query}%", limit)
            )
            return [{"id": row[0], "content": row[1], "timestamp": row[2]} for row in cursor.fetchall()]

    def evict_archival(self, mem_id: int) -> bool:
        """Evict a specific memory."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM archival_memory WHERE id = ?", (mem_id,))
            return cursor.rowcount > 0

    def insert_recall(self, event_id: str, event_type: str, payload: dict):
        """Append to the raw event log."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO recall_memory (id, event_type, timestamp, payload) VALUES (?, ?, ?, ?)",
                (event_id, event_type, datetime.utcnow().isoformat(), json.dumps(payload))
            )

    def get_recall_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, event_type, timestamp, payload FROM recall_memory ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            return [{"id": r[0], "event_type": r[1], "timestamp": r[2], "payload": json.loads(r[3])} for r in reversed(rows)]
