"""
forge/tools/memory_tools.py — Archival memory tools.

Registered tools: memory_search, memory_insert, memory_evict

These tools expose the MemoryStore's archival memory to the LLM, enabling
it to persist and retrieve information across conversation turns and sessions.
"""
from __future__ import annotations

from forge.tools import registry


@registry.register(
    name="memory_search",
    description=(
        "Search the long-term archival memory for stored facts or notes. "
        "Returns the most relevant entries for the given query."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query string."},
            "limit": {
                "type": "integer",
                "description": "Maximum number of results to return. Default 5.",
            },
        },
        "required": ["query"],
    },
)
def memory_search(query: str, limit: int = 5) -> str:
    from forge.memory.store import MemoryStore
    results = MemoryStore().search_archival(query, limit=limit)
    if not results:
        return "No matching memories found."
    return "\n".join(f"[{r['id']}] {r['timestamp']}: {r['content']}" for r in results)


@registry.register(
    name="memory_insert",
    description=(
        "Store a fact, note, or piece of information in long-term archival memory. "
        "Use this to remember things across sessions."
    ),
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The information to remember."},
        },
        "required": ["content"],
    },
)
def memory_insert(content: str) -> str:
    from forge.memory.store import MemoryStore
    mem_id = MemoryStore().insert_archival(content)
    return f"Stored as memory #{mem_id}."


@registry.register(
    name="memory_evict",
    description="Delete a specific memory entry by its numeric ID.",
    parameters={
        "type": "object",
        "properties": {
            "mem_id": {"type": "integer", "description": "Memory ID to delete."},
        },
        "required": ["mem_id"],
    },
)
def memory_evict(mem_id: int) -> str:
    from forge.memory.store import MemoryStore
    ok = MemoryStore().evict_archival(mem_id)
    return f"Memory #{mem_id} deleted." if ok else f"Memory #{mem_id} not found."
