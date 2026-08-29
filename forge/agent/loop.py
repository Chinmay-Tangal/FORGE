"""
forge/agent/loop.py — Core Agent class and agentic execution loop.

The Agent owns the LLM → tool-dispatch → observation cycle. It is stateless
between instantiations: all state lives in ConversationState.

Architecture
------------
1. ``step()``       — one LLM call + all its tool dispatches.
2. ``run()``        — calls ``step()`` repeatedly until the assistant replies
                      with no tool calls, or ``max_iterations`` is hit.
3. ``stream_run()`` — like ``run()`` but yields ``(kind, payload)`` tuples so
                      the CLI can print tokens as they arrive.

Confirmation flow
-----------------
When a tool call is HIGH-risk (or MEDIUM in strict policy), the agent emits a
``ConfirmationRequiredEvent``, sets ``state.status = "paused"``, and stores the
pending tool call in ``self._pending``. The CLI then prompts the user and calls
either ``agent.resume_confirmed()`` or ``agent.resume_denied()``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Generator, List, Optional, Tuple

from forge.config import Config
from forge.core.condenser import LLMSummarizingCondenser
from forge.core.events import (
    ConfirmationRequiredEvent, Event, Message, ToolCallAction, ToolResultObservation,
)
from forge.core.state import ConversationState
from forge.llm.router import RouterLLM
from forge.security.analyzer import SecurityAnalyzer
from forge.security.hooks import HookRunner
from forge.skills.loader import SkillLoader
from forge.tools.registry import ToolRegistry
from forge.agent import builder as _builder
from forge.agent import executor as _executor

logger = logging.getLogger(__name__)

_TOOL_CALLS_SENTINEL = "\x00TOOL_CALLS\x00"

import re as _re

def _parse_text_tool_calls(text: str) -> list:
    """
    Fallback parser: extract tool calls from plain text content when the LLM
    (e.g. Ollama) embeds them as JSON instead of returning structured tool_calls.

    Handles two common formats:
    - {"name": "write_file", "arguments": {...}}
    - {"name": "write_file", "parameters": {...}}
    """
    results = []
    # Find all top-level JSON objects in the text
    for match in _re.finditer(r'\{', text):
        start = match.start()
        depth = 0
        for i, ch in enumerate(text[start:]):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:start + i + 1]
                    try:
                        obj = json.loads(candidate)
                        name = obj.get("name")
                        args = obj.get("arguments") or obj.get("parameters") or {}
                        if name and isinstance(name, str):
                            if isinstance(args, dict):
                                args_str = json.dumps(args)
                            else:
                                args_str = str(args)
                            results.append({
                                "id": f"text_{start}",
                                "type": "function",
                                "function": {"name": name, "arguments": args_str},
                            })
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break
    return results



class Agent:
    """
    Forge's agent loop.

    Parameters
    ----------
    state:
        Mutable conversation state (event log + metadata).
    llm:
        RouterLLM wrapping local and optional frontier backends.
    registry:
        Tool registry with all registered tool functions.
    security:
        Security analyzer for risk classification and confirmation policy.
    config:
        Optional ``Config`` instance; derived from defaults if not provided.
    """

    def __init__(
        self,
        state: ConversationState,
        llm: RouterLLM,
        registry: ToolRegistry,
        security: SecurityAnalyzer,
        config: Optional[Config] = None,
    ) -> None:
        self.state = state
        self.llm = llm
        self.registry = registry
        self.security = security

        cfg = config or Config()
        self.max_iterations: int = cfg.max_iterations
        self.context_limit: int = cfg.context_limit

        self.hook_runner = HookRunner(hooks_dir=cfg.hooks_dir)
        self.skill_loader = SkillLoader(skills_dir=cfg.skills_dir)
        self.condenser = LLMSummarizingCondenser(llm=llm.local_llm)

        self.system_prompt = (
            "You are Forge, a terminal-native agentic coding assistant. "
            "You MUST use tools to perform ALL file and shell operations. "
            "NEVER print code as plain text — always call write_file or patch_file to create/modify files. "
            "NEVER describe what commands to run — always call run_shell to execute them. "
            "When asked to create a project or file, immediately call write_file with the full content. "
            "Think step-by-step, use tools for every action, and confirm results with read_file or run_shell."
        )

        # Set by the CLI to the text of the last user message for skill triggering
        self._last_user_message: str = ""
        # Pending tool call waiting for user confirmation
        self._pending: Optional[Dict[str, Any]] = None

    # Context assembly — delegates to builder module
    def _build_messages(self) -> List[Dict[str, str]]:
        return _builder.build_messages(self)

    def _maybe_condense(self) -> None:
        """Evict the oldest 33 % of events if the token budget is exceeded."""
        return _builder.maybe_condense(self)

    # Tool execution — delegates to executor module
    def _execute_tool(self, tc: Dict[str, Any]) -> Generator[Event, None, None]:
        """Execute one tool call dict and yield its action + observation events."""
        yield from _executor.execute_tool(self, tc)

    # Confirmation flow — delegates to executor module
    def resume_confirmed(self) -> Generator[Event, None, None]:
        """Execute the pending tool after user confirms it."""
        yield from _executor.resume_confirmed(self)

    def resume_denied(self) -> Generator[Event, None, None]:
        """Skip the pending tool after user denies it."""
        yield from _executor.resume_denied(self)

    # Core step
    def step(self, require_frontier: bool = False) -> Generator[Event, None, None]:
        """One LLM call → zero-or-more tool dispatches → observations."""
        if self.state.status != "active":
            return

        self._maybe_condense()

        try:
            response = self.llm.generate(
                self._build_messages(),
                self.registry.to_openai_schema(),
                require_frontier,
            )
            message = response["choices"][0]["message"]
        except Exception as exc:
            err = Message(role="system", content=f"LLM error: {exc}")
            self.state.append_event(err)
            yield err
            return

        tool_calls = message.get("tool_calls") or []

        # Fallback: some Ollama models return tool calls as JSON text content
        # instead of structured tool_calls. Parse them out if tool_calls is empty.
        if not tool_calls:
            content = message.get("content", "") or ""
            tool_calls = _parse_text_tool_calls(content)

        if tool_calls:
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                except (json.JSONDecodeError, TypeError):
                    args = {}

                if self.security.requires_confirmation(func_name, args):
                    risk = self.security.assess_risk(func_name, args)
                    evt = ConfirmationRequiredEvent(
                        tool_name=func_name,
                        tool_args=args,
                        risk=risk,
                        tool_call_raw=tc,
                    )
                    self._pending = tc
                    self.state.status = "paused"
                    self.state.append_event(evt)
                    yield evt
                    return  # CLI must call resume_confirmed / resume_denied

                yield from self._execute_tool(tc)
                if self.state.status != "active":
                    return
        else:
            msg = Message(role="assistant", content=message.get("content", ""))
            self.state.append_event(msg)
            yield msg

    # Run loops
    def run(self, require_frontier: bool = False) -> Generator[Event, None, None]:
        """
        Run ``step()`` in a loop until the assistant sends a plain-text reply
        (no tool calls) or ``max_iterations`` is reached.
        """
        for _ in range(self.max_iterations):
            events = list(self.step(require_frontier))
            yield from events
            if self.state.status != "active":
                break
            if events and isinstance(events[-1], Message) and events[-1].role == "assistant":
                break

    def stream_run(
        self, require_frontier: bool = False
    ) -> Generator[Tuple[str, Any], None, None]:
        """
        Streaming variant of ``run()``.

        Yields ``('text', chunk_str)`` for live token output and
        ``('event', Event)`` for structured events. The CLI handles both.
        """
        if self.state.status != "active":
            return

        self._maybe_condense()
        content_chunks: List[str] = []
        tool_calls_list: List[Dict[str, Any]] = []

        try:
            for chunk in self.llm.stream_generate(
                self._build_messages(),
                self.registry.to_openai_schema(),
                require_frontier,
            ):
                if chunk.startswith(_TOOL_CALLS_SENTINEL):
                    tool_calls_list = json.loads(chunk[len(_TOOL_CALLS_SENTINEL):])
                else:
                    content_chunks.append(chunk)
                    yield ("text", chunk)
        except Exception as exc:
            err = Message(role="system", content=f"LLM streaming error: {exc}")
            self.state.append_event(err)
            yield ("event", err)
            return

        if tool_calls_list:
            for tc in tool_calls_list:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                if self.security.requires_confirmation(func_name, args):
                    risk = self.security.assess_risk(func_name, args)
                    evt = ConfirmationRequiredEvent(
                        tool_name=func_name, tool_args=args,
                        risk=risk, tool_call_raw=tc,
                    )
                    self._pending = tc
                    self.state.status = "paused"
                    self.state.append_event(evt)
                    yield ("event", evt)
                    return
                for event in self._execute_tool(tc):
                    yield ("event", event)
                if self.state.status != "active":
                    return
        else:
            content = "".join(content_chunks)
            msg = Message(role="assistant", content=content)
            self.state.append_event(msg)
            yield ("event", msg)
