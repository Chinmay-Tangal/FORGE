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

import os as _os
import re as _re

_KNOWN_TOOLS = {
    "read_file", "write_file", "append_file", "delete_file",
    "list_dir", "find_files", "grep", "patch_file",
    "shell", "git_status", "git_diff", "git_log", "git_commit",
    "memory_search", "memory_insert", "memory_evict",
}


def _parse_text_tool_calls(text: str) -> list:
    """
    Extract tool calls from plain text content when the LLM embeds them
    in text (JSON, markdown code blocks, XML tags, or function call syntax).
    """
    if not text or not text.strip():
        return []

    results = []

    # 1. Look for XML tags like <tool_call>...</tool_call> or <function_call>...</function_call>
    for match in _re.finditer(r"<(?:tool_call|function_call)>(.*?)</(?:tool_call|function_call)>", text, _re.DOTALL):
        try:
            obj = json.loads(match.group(1).strip())
            name = obj.get("name") or obj.get("tool") or obj.get("function")
            args = obj.get("arguments") or obj.get("parameters") or obj.get("input") or {}
            if name in _KNOWN_TOOLS:
                args_str = json.dumps(args) if isinstance(args, dict) else str(args)
                results.append({"id": f"tc_{len(results)}", "type": "function", "function": {"name": name, "arguments": args_str}})
        except (json.JSONDecodeError, ValueError):
            pass

    if results:
        return results

    # 2. Look for JSON markdown blocks ```json ... ```
    for match in _re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, _re.DOTALL):
        try:
            obj = json.loads(match.group(1).strip())
            name = obj.get("name") or obj.get("tool")
            args = obj.get("arguments") or obj.get("parameters") or {}
            if name in _KNOWN_TOOLS:
                args_str = json.dumps(args) if isinstance(args, dict) else str(args)
                results.append({"id": f"tc_{len(results)}", "type": "function", "function": {"name": name, "arguments": args_str}})
        except (json.JSONDecodeError, ValueError):
            pass

    if results:
        return results

    # 3. Find raw JSON objects in the text
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
                        name = obj.get("name") or obj.get("tool")
                        args = obj.get("arguments") or obj.get("parameters") or {}
                        if name and name in _KNOWN_TOOLS:
                            args_str = json.dumps(args) if isinstance(args, dict) else str(args)
                            results.append({
                                "id": f"tc_{len(results)}",
                                "type": "function",
                                "function": {"name": name, "arguments": args_str},
                            })
                    except (json.JSONDecodeError, ValueError):
                        pass
                    break

    if results:
        return results

    # 4. Fallback: Parse Python-style function call syntax e.g. read_file(path="README.md") or list_dir(".")
    for fn_name in _KNOWN_TOOLS:
        pattern = rf"(?:^|\n|\s|[→>`]){fn_name}\s*\((.*?)\)"
        for m in _re.finditer(pattern, text, _re.DOTALL):
            arg_content = m.group(1).strip()
            args_dict = {}
            if not arg_content:
                args_dict = {}
            elif arg_content.startswith("{") and arg_content.endswith("}"):
                try:
                    args_dict = json.loads(arg_content)
                except Exception:
                    pass
            else:
                # Positional string argument e.g. read_file("foo.py") or read_file('foo.py')
                str_match = _re.match(r"^['\"]([^'\"]+)['\"]$", arg_content)
                if str_match:
                    val = str_match.group(1)
                    if fn_name in ("read_file", "delete_file", "list_dir", "patch_file"):
                        args_dict = {"path": val}
                    elif fn_name in ("shell",):
                        args_dict = {"command": val}
                    elif fn_name in ("find_files", "grep"):
                        args_dict = {"pattern": val}
                    elif fn_name in ("memory_search", "memory_insert"):
                        args_dict = {"query" if fn_name == "memory_search" else "content": val}
                else:
                    # Keyword arguments e.g. path="README.md"
                    for kw in _re.finditer(r"([a-zA-Z_]\w*)\s*=\s*(['\"][^'\"]*['\"]|\d+|True|False)", arg_content):
                        k, v = kw.group(1), kw.group(2)
                        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                            args_dict[k] = v[1:-1]
                        elif v.isdigit():
                            args_dict[k] = int(v)
                        elif v in ("True", "False"):
                            args_dict[k] = (v == "True")

            if args_dict or fn_name in ("list_dir", "git_status", "git_diff", "git_log"):
                results.append({
                    "id": f"tc_{len(results)}",
                    "type": "function",
                    "function": {"name": fn_name, "arguments": json.dumps(args_dict)},
                })
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

        cwd = _os.path.abspath(_os.getcwd())
        self.system_prompt = (
            "You are Forge, an autonomous terminal-native AI coding assistant and expert software engineer, modeled after Claude Code.\n"
            f"Current working directory: {cwd}\n"
            f"Operating system: {'Windows' if _os.name == 'nt' else 'POSIX'}\n\n"
            "CORE BEHAVIOR RULES:\n"
            "1. BE AUTONOMOUS AND PROACTIVE: Never ask the user for information you can find yourself. "
            "Never ask the user for file paths, directory contents, or permission to read files. "
            "Use your tools (list_dir, find_files, grep, read_file, write_file, patch_file, shell, git_status) to explore and build directly.\n"
            "2. NO CONVERSATIONAL FILLER: Do NOT say 'I will read the file', 'Please provide the path', or 'To list files I will call list_dir'. "
            "Execute the tool calls IMMEDIATELY.\n"
            "3. PLANNING WORKFLOW: When asked to create modules or run tests:\n"
            "   Step 1: Write the implementation files using `write_file`.\n"
            "   Step 2: Write the test files using `write_file`.\n"
            "   Step 3: Run the tests or verification using `shell`.\n"
            "   Never run test runners (like pytest) before creating the source and test files!\n"
            "4. FILE PATHS: All relative paths are resolved relative to the current working directory. "
            "To inspect the current directory, call list_dir(path='.'). To read a file, use its relative path (e.g. 'README.md', 'calc.py') or absolute path.\n"
            "5. NO REPETITIVE ACTIONS: Never call the exact same command repeatedly if it returns the same result. "
            "If a command returns empty or fails due to missing files, create the files first."
        )

        # Set by the CLI to the text of the last user message for skill triggering
        self._last_user_message: str = ""
        # Pending tool call waiting for user confirmation
        self._pending: Optional[Dict[str, Any]] = None
        # Track recent tool calls for loop prevention
        self._call_history: List[Tuple[str, str]] = []

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

                # Loop prevention: check if identical call was repeated
                sig = (func_name, json.dumps(args, sort_keys=True))
                if len(self._call_history) >= 2 and self._call_history[-1] == sig and self._call_history[-2] == sig:
                    nudge = Message(
                        role="user",
                        content=(
                            f"[System: `{func_name}` with arguments `{json.dumps(args)}` was called repeatedly without making progress. "
                            "If tests or commands failed because files are missing, first create the implementation and test files with `write_file`, "
                            "then run the verification command.]"
                        ),
                    )
                    self.state.append_event(nudge)
                    yield nudge
                    self._call_history.clear()
                    return

                self._call_history.append(sig)
                if len(self._call_history) > 10:
                    self._call_history.pop(0)

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
