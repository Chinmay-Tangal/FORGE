"""
forge/security/hooks.py — Pre/post-tool hook runner.

Hooks are scripts stored in ``.forge/hooks/`` following a naming convention:

    pre_<tool_name>.sh   — runs before a tool executes
    post_<tool_name>.sh  — runs after, receives FORGE_TOOL_RESULT env var

Supported script types: ``.sh`` (bash/sh), ``.ps1`` (PowerShell), ``.py`` (Python).
Tool arguments are passed as ``FORGE_ARG_<KEY>`` environment variables.

This mirrors the Antigravity CLI hooks system.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class HookRunner:
    """Discovers and executes pre/post hook scripts for tool calls."""

    def __init__(self, hooks_dir: str = ".forge/hooks") -> None:
        self.hooks_dir = os.path.abspath(hooks_dir)

    # Internal helpers
    def _hook_path(self, phase: str, tool_name: str) -> Optional[str]:
        for ext in (".sh", ".ps1", ".py"):
            path = os.path.join(self.hooks_dir, f"{phase}_{tool_name}{ext}")
            if os.path.isfile(path):
                return path
        return None

    @staticmethod
    def _executor(hook_path: str) -> list:
        ext = os.path.splitext(hook_path)[1].lower()
        if ext == ".py":
            return ["python"]
        if ext == ".ps1":
            return ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
        return ["bash"] if os.name != "nt" else ["cmd", "/c"]

    def _build_env(self, tool_args: Dict[str, Any], extra: Optional[Dict[str, str]] = None) -> dict:
        env = os.environ.copy()
        for key, val in tool_args.items():
            env[f"FORGE_ARG_{key.upper()}"] = str(val)
        if extra:
            env.update(extra)
        return env

    def _run_hook(self, hook_path: str, env: dict, timeout: int) -> Optional[str]:
        try:
            result = subprocess.run(
                self._executor(hook_path) + [hook_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                logger.warning("Hook %s exited %d: %s", hook_path, result.returncode, result.stderr)
            return result.stdout or None
        except subprocess.TimeoutExpired:
            logger.warning("Hook %s timed out.", hook_path)
            return None
        except Exception as exc:
            logger.error("Hook %s failed: %s", hook_path, exc)
            return None

    # Public API
    def run_pre_hook(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        """Run the pre-hook for a tool. Returns hook stdout, or None if no hook."""
        path = self._hook_path("pre", tool_name)
        if not path:
            return None
        return self._run_hook(path, self._build_env(tool_args), timeout=10)

    def run_post_hook(
        self, tool_name: str, tool_args: Dict[str, Any], tool_result: str
    ) -> Optional[str]:
        """Run the post-hook for a tool. Returns hook stdout, or None if no hook."""
        path = self._hook_path("post", tool_name)
        if not path:
            return None
        extra = {"FORGE_TOOL_RESULT": tool_result, "FORGE_TOOL_NAME": tool_name}
        return self._run_hook(path, self._build_env(tool_args, extra), timeout=15)
