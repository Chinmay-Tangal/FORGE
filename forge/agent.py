"""
forge/agent.py — Core agent loop.

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
    Event, Message, ToolCallAction, ToolResultObservation,
)
from forge.core.state import ConversationState
from forge.llm.router import RouterLLM
from forge.security.analyzer import SecurityAnalyzer
from forge.security.hooks import HookRunner
from forge.skills.loader import SkillLoader
from forge.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_TOOL_CALLS_SENTINEL = "\x00TOOL_CALLS\x00"


class ConfirmationRequiredEvent(Event):
    """Emitted when a tool call requires user confirmation before it can execute."""

    source: str = "system"
    tool_name: str
    tool_args: Dict[str, Any]
    risk: str
    tool_call_raw: Dict[str, Any]  # original tool_call dict; stored for resume


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
            "You are Forge, a helpful and highly capable terminal-native local agentic "
            "coding assistant. You have access to tools to read/write files, run shell "
            "commands, search code, and manage memory.\n"
            "Always prefer targeted edits (patch_file) over full rewrites (write_file) "
            "for existing files. Think step-by-step before taking irreversible actions."
        )

        # Set by the CLI to the text of the last user message for skill triggering
        self._last_user_message: str = ""
        # Pending tool call waiting for user confirmation
        self._pending: Optional[Dict[str, Any]] = None

    # Context assembly
    def _build_messages(self) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        skill_ctx = self.skill_loader.build_system_context(self._last_user_message)
        if skill_ctx:
            messages.append({"role": "system", "content": skill_ctx})
        if self.state.working_context:
            messages.append({
                "role": "system",
                "content": f"Condensed history:\n{self.state.working_context}",
            })
        for msg in self.state.get_recent_messages(limit=20):
            messages.append({"role": msg.role, "content": msg.content})
        return messages

    def _maybe_condense(self) -> None:
        """Evict the oldest 30 % of events if the token budget is exceeded."""
        total = self.llm.count_tokens(
            " ".join(
                getattr(e, "content", "") or str(e.model_dump())
                for e in self.state.events
            )
        )
        if total < self.context_limit:
            return
        evict_n = max(1, len(self.state.events) // 3)
        to_evict, self.state.events = self.state.events[:evict_n], self.state.events[evict_n:]
        try:
            self.state.working_context = self.condenser.condense(
                to_evict, self.state.working_context
            )
            logger.info("Condensed %d events.", evict_n)
        except Exception as exc:
            logger.warning("Condenser failed (%s). Events evicted without summary.", exc)

    # Tool execution
    def _execute_tool(self, tc: Dict[str, Any]) -> Generator[Event, None, None]:
        """Execute one tool call dict and yield its action + observation events."""
        func_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            args = {}

        action = ToolCallAction(tool_name=func_name, tool_args=args)
        self.state.append_event(action)
        yield action

        self.hook_runner.run_pre_hook(func_name, args)

        try:
            result = self.registry.execute(func_name, args)
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

        self.hook_runner.run_post_hook(func_name, args, obs.content)
        self.state.append_event(obs)
        yield obs

        # Feed result back as a user message so the next LLM call sees it
        self.state.append_event(
            Message(role="user", content=f"Tool `{func_name}` returned:\n{obs.content}")
        )

    # Confirmation flow
    def resume_confirmed(self) -> Generator[Event, None, None]:
        """Execute the pending tool after user confirms it."""
        if not self._pending:
            return
        tc, self._pending = self._pending, None
        self.state.status = "active"
        yield from self._execute_tool(tc)

    def resume_denied(self) -> Generator[Event, None, None]:
        """Skip the pending tool after user denies it."""
        if not self._pending:
            return
        func_name = self._pending["function"]["name"]
        self._pending = None
        self.state.status = "active"
        msg = Message(
            role="system",
            content=f"User denied `{func_name}`. Skipping that action.",
        )
        self.state.append_event(msg)
        yield msg

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
        if tool_calls:
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
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
