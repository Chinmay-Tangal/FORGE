"""
forge/agent/subagent.py — Multi-agent delegation and task specialization.

Allows the primary agent to spawn focused, isolated subagents (e.g., Codebase Researcher,
Test Specialist, Security Reviewer) with bounded iterations and dedicated system prompts.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from forge.core.events import Event, Message
from forge.core.state import ConversationState
from forge.tools import registry
from forge.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from forge.agent.loop import Agent
    from forge.llm.router import RouterLLM
    from forge.security.analyzer import SecurityAnalyzer

logger = logging.getLogger(__name__)

_SUBAGENT_ROLES = {
    "researcher": (
        "You are an expert Codebase Researcher subagent. Your goal is to explore, inspect, "
        "and analyze the codebase to answer the user's specific inquiry. "
        "Use `read_file`, `list_dir`, `find_files`, `grep`, `get_code_outline`, and `find_symbol`. "
        "Synthesize your findings into a dense, factual report."
    ),
    "tester": (
        "You are a Quality & Test Specialist subagent. Your goal is to execute test suites, "
        "diagnose failures, examine tracebacks, and pinpoint root causes. "
        "Use `shell`, `read_file`, and `git_diff`. Conclude with a clear root-cause breakdown."
    ),
    "reviewer": (
        "You are a Senior Code Reviewer & Security Auditor subagent. Your goal is to inspect proposed "
        "changes, diffs, and implementations for bugs, edge cases, security vulnerabilities, or performance regressions. "
        "Use `git_diff`, `read_file`, and `get_code_outline`."
    ),
    "general": (
        "You are a specialized autonomous subagent tasked with completing a bounded objective. "
        "Use your tools efficiently and report your final outcome clearly."
    ),
}


class SubAgentRunner:
    """Spawns and executes an isolated subagent on behalf of the primary agent."""

    def __init__(
        self,
        llm: "RouterLLM",
        tool_registry: ToolRegistry,
        security: "SecurityAnalyzer",
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.registry = tool_registry
        self.security = security
        self.max_iterations = max_iterations

    def run_task(
        self,
        role: str,
        task: str,
        target_files: Optional[List[str]] = None,
    ) -> str:
        """Execute a subagent task to completion and return the final synthesis."""
        from forge.agent.loop import Agent
        from forge.config import Config

        role_key = role.lower().strip()
        role_prompt = _SUBAGENT_ROLES.get(role_key, _SUBAGENT_ROLES["general"])

        files_ctx = f"\nRelevant files: {', '.join(target_files)}" if target_files else ""
        system_prompt = f"{role_prompt}\n\nTask: {task}{files_ctx}"

        sub_state = ConversationState()
        sub_state.append_event(Message(role="user", content=task))

        cfg = Config(max_iterations=self.max_iterations)
        sub_agent = Agent(
            state=sub_state,
            llm=self.llm,
            registry=self.registry,
            security=self.security,
            config=cfg,
        )
        sub_agent.system_prompt = system_prompt

        logger.info("Spawning subagent [%s] for task: %s", role_key, task[:80])

        events: List[Event] = []
        try:
            for event in sub_agent.run():
                events.append(event)
        except Exception as exc:
            logger.error("Subagent [%s] execution error: %s", role_key, exc)
            return f"Subagent [{role_key}] failed with error: {exc}"

        # Extract final assistant response
        assistant_messages = [e for e in events if isinstance(e, Message) and e.role == "assistant" and e.content]
        if assistant_messages:
            return assistant_messages[-1].content

        return f"Subagent [{role_key}] completed task ({len(events)} events processed)."


# Global runner reference set by Agent during initialization
_global_subagent_runner: Optional[SubAgentRunner] = None


def set_subagent_runner(runner: SubAgentRunner) -> None:
    global _global_subagent_runner
    _global_subagent_runner = runner


@registry.register(
    name="delegate_task",
    description=(
        "Spawn a specialized subagent to handle a focused sub-task without cluttering the main context. "
        "Roles: 'researcher' (codebase search & analysis), 'tester' (run tests & debug tracebacks), "
        "'reviewer' (code review & security audit), or 'general'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "enum": ["researcher", "tester", "reviewer", "general"],
                "description": "Specialized role for the subagent.",
            },
            "task": {"type": "string", "description": "Specific objective for the subagent to complete."},
            "target_files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of relevant files.",
            },
        },
        "required": ["role", "task"],
    },
)
def delegate_task(role: str, task: str, target_files: list[str] | None = None) -> str:
    if _global_subagent_runner is None:
        return "Subagent runner is not initialized."
    return _global_subagent_runner.run_task(role=role, task=task, target_files=target_files)
