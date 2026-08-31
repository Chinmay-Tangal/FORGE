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

from forge.core.events import (
    Event,
    FileReadObservation,
    Message,
    ShellCommandObservation,
    ToolCallAction,
    ToolResultObservation,
)

if TYPE_CHECKING:
    from forge.llm.backend import LLMBackend

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a concise context-summarization assistant for an agentic coding environment. "
    "Summarize the provided events into a dense, factual bulleted summary preserving:\n"
    "- User goals and decisions\n"
    "- Files created, read, or modified\n"
    "- Shell commands run and outcomes\n"
    "- Current status and next steps\n"
    "Keep the summary under 150 words. Output ONLY the summary."
)


def format_event_for_summary(event: Event) -> str:
    """Produce a compact, human-readable one-line description of an event."""
    if isinstance(event, Message):
        content = (event.content or "").strip()
        if len(content) > 200:
            content = content[:200] + "…"
        if event.tool_calls:
            tc_names = [tc.get("function", {}).get("name", "tool") for tc in event.tool_calls]
            return f"[Assistant] Invoked tools: {', '.join(tc_names)}"
        return f"[{event.role.capitalize()}] {content}"
    elif isinstance(event, ToolCallAction):
        args_str = str(event.tool_args)
        if len(args_str) > 100:
            args_str = args_str[:100] + "…"
        return f"[Tool Call] {event.tool_name}({args_str})"
    elif isinstance(event, ToolResultObservation):
        content = (event.content or "").strip()
        status = "Success" if event.success else "Failed"
        if len(content) > 150:
            content = content[:150] + "…"
        return f"[Tool Result: {event.tool_name} - {status}] {content}"
    elif isinstance(event, ShellCommandObservation):
        return f"[Shell Exit {event.exit_code}] {event.command}"
    elif isinstance(event, FileReadObservation):
        return f"[File Read] {event.path}"
    else:
        text = str(getattr(event, "content", "")) or type(event).__name__
        return f"[{type(event).__name__}] {text[:100]}"


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
        formatted_lines = [format_event_for_summary(e) for e in events]
        events_text = "\n".join(formatted_lines)

        # Cap text sent to condenser to prevent 400 Bad Request on local models with small context
        if len(events_text) > 3000:
            events_text = events_text[:3000] + "\n… [older events truncated]"

        user_content = ""
        if previous_summary:
            prev = previous_summary if len(previous_summary) < 1000 else previous_summary[:1000] + "…"
            user_content += f"Previous context summary:\n{prev}\n\n"
        user_content += f"Recent events to summarise:\n{events_text}"

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            response = self.llm.generate(messages)
            summary = response["choices"][0]["message"]["content"].strip()
            if summary:
                return summary
        except Exception as exc:
            logger.warning("Condenser LLM call failed: %s", exc)

        # Clean structured fallback without raw JSON dumps
        fallback_lines = []
        if previous_summary:
            fallback_lines.append(previous_summary[:500])
        fallback_lines.extend(formatted_lines[-8:])
        return "\n".join(fallback_lines)[:1000]
