"""
forge/core/condenser.py — LLM-based context eviction and compression.

When the agent's in-context event log grows too large, the Condenser
summarises the oldest events into a short paragraph stored in
ConversationState.working_context, then those events are evicted.

This mirrors the MemGPT recursive-compression pattern (arXiv:2310.08560).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from forge.core.events import Event

if TYPE_CHECKING:
    from forge.llm.backend import LLMBackend

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a concise summarisation assistant. "
    "Summarise the provided conversation events into a short, dense paragraph "
    "that preserves all decisions made, files edited, commands run, and key facts. "
    "Output only the summary — no preamble."
)


class LLMSummarizingCondenser:
    """Compresses evicted events into a running working-context summary."""

    def __init__(self, llm: "LLMBackend") -> None:
        self.llm = llm

    def condense(self, events: List[Event], previous_summary: str = "") -> str:
        """
        Summarise `events` into a new working-context string.

        Parameters
        ----------
        events:
            The events being evicted from the active context window.
        previous_summary:
            The existing working_context to fold into the new summary.
        """
        events_text = "\n".join(
            f"[{type(e).__name__}] {e.model_dump_json()}" for e in events
        )
        user_content = ""
        if previous_summary:
            user_content += f"Previous context summary:\n{previous_summary}\n\n"
        user_content += f"Events to summarise:\n{events_text}"

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            response = self.llm.generate(messages)
            return response["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.warning("Condenser LLM call failed: %s", exc)
            # Fallback: return a simple truncated concatenation
            return (previous_summary + "\n" + events_text)[:2000]
