"""
forge/agent/builder.py — Message assembly and context compression.

Provides the build_messages() and maybe_condense() helpers used by the Agent
loop. Extracted into their own module to keep loop.py focused solely on the
agentic execution cycle.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from forge.agent.loop import Agent

logger = logging.getLogger(__name__)


def build_messages(agent: "Agent") -> List[Dict[str, Any]]:
    """
    Assemble the messages list for the next LLM call.

    Order: base system prompt → skill/project context → condensed history
    summary → last 25 in-context events.
    """
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": agent.system_prompt}
    ]
    skill_ctx = agent.skill_loader.build_system_context(agent._last_user_message)
    if skill_ctx:
        messages.append({"role": "system", "content": skill_ctx})
    if agent.state.working_context:
        messages.append({
            "role": "system",
            "content": f"Condensed history:\n{agent.state.working_context}",
        })
    for msg in agent.state.get_recent_messages(limit=25):
        m: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
        if msg.role == "assistant" and msg.tool_calls:
            m["tool_calls"] = msg.tool_calls
        elif msg.role == "tool":
            m["tool_call_id"] = msg.tool_call_id or "call_0"
            if msg.name:
                m["name"] = msg.name
        messages.append(m)
    return messages


def maybe_condense(agent: "Agent") -> None:
    """Evict the oldest 33 % of events if the token budget is exceeded."""
    total = agent.llm.count_tokens(
        " ".join(
            getattr(e, "content", "") or str(e.model_dump())
            for e in agent.state.events
        )
    )
    if total < agent.context_limit:
        return
    evict_n = max(1, len(agent.state.events) // 3)
    to_evict, agent.state.events = agent.state.events[:evict_n], agent.state.events[evict_n:]
    try:
        agent.state.working_context = agent.condenser.condense(
            to_evict, agent.state.working_context
        )
        logger.info("Condensed %d events.", evict_n)
    except Exception as exc:
        logger.warning("Condenser failed (%s). Events evicted without summary.", exc)
