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
import os as _os
import re as _re
from typing import Any, Dict, Generator, List, Optional, Tuple

from forge.agent import builder as _builder
from forge.agent import executor as _executor
from forge.config import Config
from forge.core.condenser import LLMSummarizingCondenser
from forge.core.events import (
    ConfirmationRequiredEvent,
    Event,
    Message,
)
from forge.core.state import ConversationState
from forge.llm.router import RouterLLM
from forge.security.analyzer import SecurityAnalyzer
from forge.security.hooks import HookRunner
from forge.skills.loader import SkillLoader
from forge.tools.registry import ToolRegistry
from forge.workspace.grounding import get_workspace_grounding

logger = logging.getLogger(__name__)

_TOOL_CALLS_SENTINEL = "\x00TOOL_CALLS\x00"

_KNOWN_TOOLS = {
    "read_file", "write_file", "edit_file", "append_file", "delete_file",
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

    if results:
        return results

    # 5. Extract files from markdown code blocks with filepath headings
    # e.g. ### forge/utils/bench.py\n```python\n<code>```
    file_block_re = _re.compile(
        r"(?:###|\*\*|File:|\#)\s*`?([a-zA-Z0-9_./\\-]+\.[a-zA-Z0-9]+)`?\s*(?:\*\*)?\s*\n+```[a-zA-Z0-9_-]*\n(.*?)```",
        _re.DOTALL,
    )
    for m in file_block_re.finditer(text):
        fpath = m.group(1).strip().replace("\\", "/").strip("`")
        fcontent = m.group(2)
        if "/" in fpath or fpath.endswith((".py", ".html", ".css", ".js", ".json", ".md", ".toml", ".sh", ".txt", ".yml", ".yaml")):
            results.append({
                "id": f"tc_{len(results)}",
                "type": "function",
                "function": {"name": "write_file", "arguments": json.dumps({"path": fpath, "content": fcontent})},
            })

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
        grounding = get_workspace_grounding(cwd)

        self.system_prompt = (
            "You are Forge, an elite autonomous terminal-native AI coding assistant and expert software engineer, modeled after Claude Code and Cursor.\n\n"
            f"{grounding}\n\n"
            "OPERATING ENVIRONMENT & CAPABILITIES:\n"
            f"- Current Working Directory: {cwd}\n"
            f"- Operating System: {'Windows' if _os.name == 'nt' else 'POSIX'}\n"
            "- You have direct read, write, and execute access in this workspace through your tools.\n\n"
            "CRITICAL AUTONOMY DIRECTIVES:\n"
            "1. DIRECT ACTION OVER CHAT: Never describe code changes or output raw file contents in chat when asked to create, edit, or apply changes to files. "
            "You MUST call `write_file`, `edit_file`, or `patch_file` to write the changes directly to disk.\n"
            "2. NEVER CLAIM LACK OF ACCESS: You have complete access to the project workspace via tools. "
            "Never say 'I don't have access to files', 'I am not associated with any repository', or 'Please provide the file contents'. "
            "Use `read_file`, `list_dir`, `find_files`, `grep`, and `git_status` to inspect files directly.\n"
            "3. REPO & PROJECT AWARENESS: You are running directly inside the user's project. "
            "When asked about the project or repository, reference the workspace files, README, and git branch.\n"
            "4. WORKFLOW FOR BUILDING & FIXING:\n"
            "   - Step 1: Inspect existing files using `read_file` or `list_dir` to understand structure and style.\n"
            "   - Step 2: Make modifications or create files using `write_file` or `edit_file`.\n"
            "   - Step 3: Verify your work using `shell` or test runners.\n"
            "5. EDITING FILES: Prefer `edit_file` for targeted string replacements in existing files. Use `write_file` when creating new files or doing complete rewrites.\n"
            "6. NO REPETITIVE FAILING COMMANDS: If a command fails because a file is missing, create the file before re-running."
        )

        # Set by the CLI to the text of the last user message for skill triggering
        self._last_user_message: str = ""
        # Pending tool call waiting for user confirmation
        self._pending: Optional[Dict[str, Any]] = None
        # Track recent tool calls for loop prevention
        self._call_history: List[Tuple[str, str]] = []
        # Track consecutive guidance nudges to prevent infinite loops
        self._nudge_count: int = 0

    # Context assembly — delegates to builder module
    def _build_messages(self) -> List[Dict[str, Any]]:
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
            self._nudge_count = 0
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
            content = (message.get("content") or "").strip()
            lower_content = content.lower()

            # Guardrail 1: Check if the model falsely claimed lack of access
            lack_of_access_patterns = (
                "don't have access to", "do not have access to",
                "cannot access files", "can't access files",
                "don't have access to a website", "don't have access to the current files",
                "please provide the current content", "if you provide the current content",
                "please provide the content", "not currently associated with any specific repository"
            )
            if self._nudge_count < 2 and any(pat in lower_content for pat in lack_of_access_patterns):
                self._nudge_count += 1
                nudge = Message(
                    role="user",
                    content=(
                        "[System Guidance: You have full access to tools to inspect and modify the repository directly. "
                        "Use `list_dir`, `find_files`, `read_file`, or `git_status` to access the files. "
                        "Do not ask the user for file contents or state that you lack access.]"
                    ),
                )
                self.state.append_event(nudge)
                yield nudge
                return

            # Guardrail 2: Check if user requested a file change, but model returned text/code without invoking a tool
            user_wants_file_action = any(
                kw in self._last_user_message.lower()
                for kw in ("make", "create", "write", "update", "edit", "apply", "change", "add", "fix", "html", "landing page", "index.html", "readme")
            )
            has_code_or_claim = (
                ("```" in content)
                or ("i'll update" in lower_content)
                or ("i'll apply" in lower_content)
                or ("i've applied" in lower_content)
                or ("here's the updated" in lower_content)
                or ("here is the updated" in lower_content)
            )
            if self._nudge_count < 2 and user_wants_file_action and has_code_or_claim:
                self._nudge_count += 1
                nudge = Message(
                    role="user",
                    content=(
                        "[System Guidance: You provided code in text, but you did not execute `write_file` or `edit_file`. "
                        "The file on disk has NOT been updated. "
                        "Please invoke `write_file(path=..., content=...)` or `edit_file` now to write the changes directly to disk.]"
                    ),
                )
                self.state.append_event(nudge)
                yield nudge
                return

            self._nudge_count = 0
            msg = Message(role="assistant", content=content)
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
