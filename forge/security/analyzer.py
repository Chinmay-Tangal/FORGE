"""
forge/security/analyzer.py — Risk classification and confirmation policy.

Every tool call passes through the SecurityAnalyzer before execution.
The analyzer classifies the call as low / medium / high risk and decides
whether the user must confirm it based on the active policy.

Policies
--------
auto   (default)  — only HIGH-risk actions require confirmation.
strict            — MEDIUM and HIGH risk actions require confirmation.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Tools that are definitively read-only and safe.
_LOW_RISK_TOOLS = frozenset({
    "read_file", "list_dir", "find_files", "grep",
    "memory_search", "git_status", "git_diff", "git_log",
    "get_code_outline", "find_symbol", "find_references",
})

# Tools that mutate state but are recoverable.
_MEDIUM_RISK_TOOLS = frozenset({
    "write_file", "edit_file", "append_file", "patch_file",
    "memory_insert", "memory_evict", "git_commit", "delegate_task",
})

# Shell sub-strings that escalate a shell command to HIGH risk.
_HIGH_RISK_SHELL_PATTERNS = ("rm ", "rmdir", "del ", "format", "mkfs",
                              "dd if", "sudo", ":(){", "fork bomb")

# Shell sub-strings that keep a shell command at LOW risk.
_LOW_RISK_SHELL_PATTERNS = ("echo ", "ls ", "dir ", "cat ", "type ",
                             "pwd", "grep ", "git status", "git diff",
                             "git log", "python --version", "pip list")


class SecurityAnalyzer:
    """
    Evaluates the risk of a proposed tool call and enforces a confirmation
    policy before high-risk actions are executed.
    """

    def __init__(self, policy: str = "auto") -> None:
        if policy not in ("auto", "strict"):
            raise ValueError(f"Unknown security policy: {policy!r}. Use 'auto' or 'strict'.")
        self.policy = policy

    def assess_risk(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Classify a tool call as 'low', 'medium', or 'high' risk.

        Returns
        -------
        str
            One of ``'low'``, ``'medium'``, or ``'high'``.
        """
        if tool_name in _LOW_RISK_TOOLS:
            return "low"

        if tool_name in _MEDIUM_RISK_TOOLS:
            return "medium"

        if tool_name == "delete_file":
            return "high"

        if tool_name == "shell":
            command = args.get("command", "").lower()
            if any(p in command for p in _HIGH_RISK_SHELL_PATTERNS):
                return "high"
            if any(p in command for p in _LOW_RISK_SHELL_PATTERNS):
                return "low"
            return "medium"

        # Unknown tools default to medium — better safe than sorry.
        return "medium"

    def requires_confirmation(self, tool_name: str, args: Dict[str, Any]) -> bool:
        """Return True if this action must be confirmed by the user."""
        risk = self.assess_risk(tool_name, args)
        if self.policy == "strict":
            return risk in ("medium", "high")
        # auto policy
        return risk == "high"
