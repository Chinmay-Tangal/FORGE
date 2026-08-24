import json
import logging
from typing import List, Dict, Any, Generator, Optional

from forge_core.state import ConversationState
from forge_core.events import (
    Message, ToolCallAction, ToolResultObservation, Event,
)
from forge_core.llm import RouterLLM
from forge_tools.registry import ToolRegistry
from forge_core.security import SecurityAnalyzer
from forge_core.hooks import HookRunner
from forge_core.skills import SkillLoader
from forge_core.condenser import LLMSummarizingCondenser

logger = logging.getLogger(__name__)

# Sentinel emitted by stream_generate when tool calls finish buffering
_TOOL_CALLS_SENTINEL = "\x00TOOL_CALLS\x00"


class ConfirmationRequiredEvent(Event):
    """Emitted when a tool call requires user confirmation before execution."""
    source: str = "system"
    tool_name: str
    tool_args: Dict[str, Any]
    risk: str
    tool_call_raw: Dict[str, Any]  # original tool_call dict for resume


class Agent:
    def __init__(
        self,
        state: ConversationState,
        llm: RouterLLM,
        registry: ToolRegistry,
        security: SecurityAnalyzer,
        config=None,           # forge_core.config.Config (optional for back-compat)
        hooks_dir: str = ".forge/hooks",
        skills_dir: str = ".forge/skills",
    ):
        self.state = state
        self.llm = llm
        self.registry = registry
        self.security = security
        self.config = config

        # Derive dirs from config if provided
        if config is not None:
            hooks_dir = config.hooks_dir
            skills_dir = config.skills_dir

        self.hook_runner = HookRunner(hooks_dir=hooks_dir)
        self.skill_loader = SkillLoader(skills_dir=skills_dir)
        self.condenser = LLMSummarizingCondenser(llm=llm.local_llm)

        self.system_prompt = (
            "You are Forge, a helpful and highly capable terminal-native local agentic "
            "coding assistant. You have access to tools to read/write files, run shell "
            "commands, search code, and manage memory. Always prefer targeted edits over "
            "full rewrites. Think step-by-step before taking irreversible actions."
        )
        self.max_iterations = config.max_iterations if config else 30
        self.context_limit = config.context_limit if config else 6000

        # Pending confirmation state
        self._pending_confirmation: Optional[Dict[str, Any]] = None
        # Last user message (for skill triggering)
        self._last_user_message: str = ""

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_messages(self, user_message: str = "") -> List[Dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]

        # Inject skills context (project instructions + always-on + triggered)
        skill_context = self.skill_loader.build_system_context(user_message)
        if skill_context:
            messages.append({"role": "system", "content": skill_context})

        if self.state.working_context:
            messages.append({
                "role": "system",
                "content": f"Working context (condensed history):\n{self.state.working_context}",
            })

        for msg in self.state.get_recent_messages(limit=20):
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def _maybe_condense(self):
        """
        If the event log is getting large, condense the oldest 30% into a
        summary stored in state.working_context, then evict those events.
        """
        total_tokens = self.llm.count_tokens(
            " ".join(
                e.content if hasattr(e, "content") else str(e.model_dump())
                for e in self.state.events
            )
        )
        if total_tokens < self.context_limit:
            return

        evict_count = max(1, len(self.state.events) // 3)
        to_evict = self.state.events[:evict_count]
        self.state.events = self.state.events[evict_count:]

        try:
            summary = self.condenser.condense(to_evict, self.state.working_context)
            self.state.working_context = summary
            logger.info(f"Condensed {evict_count} events into working context.")
        except Exception as e:
            logger.warning(f"Condenser failed: {e}. Evicted events without summary.")

    # ------------------------------------------------------------------
    # Tool execution (shared between step() and resume_confirmed())
    # ------------------------------------------------------------------

    def _execute_tool(self, tc: Dict[str, Any]) -> Generator[Event, None, None]:
        """Execute a single tool call dict and yield the observation."""
        func_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except json.JSONDecodeError:
            args = {}

        action = ToolCallAction(tool_name=func_name, tool_args=args)
        self.state.append_event(action)
        yield action

        # Run pre-hook
        pre_out = self.hook_runner.run_pre_hook(func_name, args)
        if pre_out:
            logger.debug(f"Pre-hook output for {func_name}: {pre_out[:200]}")

        # Execute the tool
        try:
            result = self.registry.execute(func_name, args)
            obs = ToolResultObservation(
                tool_name=func_name,
                tool_call_id=tc.get("id", ""),
                content=str(result),
            )
        except Exception as e:
            obs = ToolResultObservation(
                tool_name=func_name,
                tool_call_id=tc.get("id", ""),
                content=str(e),
                success=False,
            )

        # Run post-hook
        self.hook_runner.run_post_hook(func_name, args, obs.content)

        self.state.append_event(obs)
        yield obs

        # Feed tool result back as a user message (OpenAI format)
        feedback = Message(
            role="user",
            content=f"Tool `{func_name}` returned:\n{obs.content}",
        )
        self.state.append_event(feedback)

    # ------------------------------------------------------------------
    # Confirmation flow
    # ------------------------------------------------------------------

    def resume_confirmed(self) -> Generator[Event, None, None]:
        """
        Called by the CLI after the user confirms a high-risk action.
        Executes the pending tool and reactivates the agent.
        """
        if not self._pending_confirmation:
            return
        tc = self._pending_confirmation
        self._pending_confirmation = None
        self.state.status = "active"
        yield from self._execute_tool(tc)

    def resume_denied(self) -> Generator[Event, None, None]:
        """
        Called by the CLI when the user denies a high-risk action.
        Logs the denial and reactivates the agent.
        """
        if self._pending_confirmation:
            func_name = self._pending_confirmation["function"]["name"]
            self._pending_confirmation = None
            self.state.status = "active"
            msg = Message(
                role="system",
                content=f"User denied execution of `{func_name}`. Continuing without it.",
            )
            self.state.append_event(msg)
            yield msg

    # ------------------------------------------------------------------
    # Core step
    # ------------------------------------------------------------------

    def step(self, require_frontier: bool = False) -> Generator[Event, None, None]:
        """Executes a single LLM → tool-call(s) → observation step."""
        if self.state.status != "active":
            return

        self._maybe_condense()

        messages = self._build_messages(self._last_user_message)
        tools = self.registry.to_openai_schema()

        try:
            response = self.llm.generate(messages, tools, require_frontier)
            message = response["choices"][0]["message"]
        except Exception as e:
            err = Message(role="system", content=f"LLM Error: {e}")
            self.state.append_event(err)
            yield err
            return

        if "tool_calls" in message and message["tool_calls"]:
            for tc in message["tool_calls"]:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                # Security check
                if self.security.requires_confirmation(func_name, args):
                    risk = self.security.assess_risk(func_name, args)
                    evt = ConfirmationRequiredEvent(
                        tool_name=func_name,
                        tool_args=args,
                        risk=risk,
                        tool_call_raw=tc,
                    )
                    self._pending_confirmation = tc
                    self.state.status = "paused"
                    self.state.append_event(evt)
                    yield evt
                    return  # CLI must resume

                yield from self._execute_tool(tc)

                if self.state.status != "active":
                    return
        else:
            msg = Message(role="assistant", content=message.get("content", ""))
            self.state.append_event(msg)
            yield msg

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self, require_frontier: bool = False) -> Generator[Event, None, None]:
        """Run the agent loop until it stops issuing tool calls or hits max_iterations."""
        for _ in range(self.max_iterations):
            events = list(self.step(require_frontier))
            for e in events:
                yield e

            if self.state.status != "active":
                break

            # If the last event was a final assistant message with no tool calls, done.
            if events and isinstance(events[-1], Message) and events[-1].role == "assistant":
                break

    def stream_run(self, require_frontier: bool = False) -> Generator[Any, None, None]:
        """
        Streaming run: yields (event_type, payload) tuples.
        - ('text', str)        — live token text from assistant
        - ('event', Event)     — structured events (tool calls, observations, etc.)
        Callers should handle both gracefully.
        """
        if self.state.status != "active":
            return

        self._maybe_condense()

        messages = self._build_messages(self._last_user_message)
        tools = self.registry.to_openai_schema()

        # Accumulate streaming output
        full_text = []
        tool_calls_list = []

        try:
            for chunk in self.llm.stream_generate(messages, tools, require_frontier):
                if chunk.startswith(_TOOL_CALLS_SENTINEL):
                    tool_calls_list = json.loads(chunk[len(_TOOL_CALLS_SENTINEL):])
                else:
                    full_text.append(chunk)
                    yield ("text", chunk)
        except Exception as e:
            err = Message(role="system", content=f"LLM Streaming Error: {e}")
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
                        tool_name=func_name,
                        tool_args=args,
                        risk=risk,
                        tool_call_raw=tc,
                    )
                    self._pending_confirmation = tc
                    self.state.status = "paused"
                    self.state.append_event(evt)
                    yield ("event", evt)
                    return

                for event in self._execute_tool(tc):
                    yield ("event", event)

                if self.state.status != "active":
                    return
        else:
            content = "".join(full_text)
            msg = Message(role="assistant", content=content)
            self.state.append_event(msg)
            yield ("event", msg)
