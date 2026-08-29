"""
forge/agent/executor.py — Tool dispatch and confirmation flow.

Handles single tool-call execution (pre-hook → registry → post-hook →
observation) and the confirmation resume/deny flow for high-risk actions.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, Generator

from forge.core.events import Event, Message, ToolCallAction, ToolResultObservation

if TYPE_CHECKING:
    from forge.agent.loop import Agent

logger = logging.getLogger(__name__)


def execute_tool(
    agent: "Agent", tc: Dict[str, Any]
) -> Generator[Event, None, None]:
    """
    Execute one tool call dict and yield its action + observation events.

    Flow: parse args → emit ToolCallAction → run pre-hook →
    execute via registry → run post-hook → emit ToolResultObservation →
    feed result back as a user Message.
    """
    func_name = tc["function"]["name"]
    raw_args = tc["function"].get("arguments", {})
    if isinstance(raw_args, dict):
        args = raw_args
    else:
        try:
            args = json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            args = {}

    action = ToolCallAction(tool_name=func_name, tool_args=args)
    agent.state.append_event(action)
    yield action

    agent.hook_runner.run_pre_hook(func_name, args)

    try:
        result = agent.registry.execute(func_name, args)
        obs = ToolResultObservation(
            tool_name=func_name,
            tool_call_id=tc.get("id", ""),
            content=str(result),
        )
    except Exception as exc:
        obs = ToolResultObservation(
            tool_name=func_name,
            tool_call_id=tc.get("id", ""),
            content=str(exc),
            success=False,
        )

    agent.hook_runner.run_post_hook(func_name, args, obs.content)
    agent.state.append_event(obs)
    yield obs

    # Feed both assistant action and tool result back so the LLM sees the complete chain
    agent.state.append_event(
        Message(role="assistant", content=f"```json\n{{\"name\": \"{func_name}\", \"arguments\": {json.dumps(args)}}}\n```")
    )
    agent.state.append_event(
        Message(role="user", content=f"Tool `{func_name}` returned:\n{obs.content}")
    )


def resume_confirmed(agent: "Agent") -> Generator[Event, None, None]:
    """Execute the pending tool after user confirms it."""
    if not agent._pending:
        return
    tc, agent._pending = agent._pending, None
    agent.state.status = "active"
    yield from execute_tool(agent, tc)


def resume_denied(agent: "Agent") -> Generator[Event, None, None]:
    """Skip the pending tool after user denies it."""
    if not agent._pending:
        return
    func_name = agent._pending["function"]["name"]
    agent._pending = None
    agent.state.status = "active"
    msg = Message(
        role="system",
        content=f"User denied `{func_name}`. Skipping that action.",
    )
    agent.state.append_event(msg)
    yield msg
