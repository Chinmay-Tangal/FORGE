"""
forge_core/hooks.py — Pre/post-tool hook runner.

Hooks are shell scripts stored in .forge/hooks/ following a naming convention:
  pre_<tool_name>.sh  — runs before a tool executes
  post_<tool_name>.sh — runs after a tool executes, receives FORGE_TOOL_RESULT env var

This mirrors the Antigravity CLI hooks system and OpenHands extension model.
"""
import os
import subprocess
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class HookRunner:
    """
    Discovers and executes pre/post hook scripts for tool calls.
    Hook scripts receive tool arguments as environment variables prefixed with FORGE_ARG_.
    """

    def __init__(self, hooks_dir: str = ".forge/hooks"):
        self.hooks_dir = os.path.abspath(hooks_dir)

    def _hook_path(self, phase: str, tool_name: str) -> Optional[str]:
        """Returns the path to a hook script if it exists."""
        candidates = [
            os.path.join(self.hooks_dir, f"{phase}_{tool_name}.sh"),
            os.path.join(self.hooks_dir, f"{phase}_{tool_name}.ps1"),
            os.path.join(self.hooks_dir, f"{phase}_{tool_name}.py"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                return path
        return None

    def _build_env(self, tool_args: Dict[str, Any], extra: Dict[str, str] = None) -> dict:
        """Builds the environment dict for hook execution."""
        env = os.environ.copy()
        for key, val in tool_args.items():
            env[f"FORGE_ARG_{key.upper()}"] = str(val)
        if extra:
            env.update(extra)
        return env

    def run_pre_hook(self, tool_name: str, tool_args: Dict[str, Any]) -> Optional[str]:
        """
        Run the pre-hook for a tool. Returns hook stdout if hook exists, else None.
        If the hook exits with non-zero, logs a warning but does not block execution.
        """
        hook_path = self._hook_path("pre", tool_name)
        if not hook_path:
            return None

        env = self._build_env(tool_args)
        try:
            result = subprocess.run(
                self._get_executor(hook_path) + [hook_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.warning(
                    f"Pre-hook for {tool_name} exited with {result.returncode}: {result.stderr}"
                )
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.warning(f"Pre-hook for {tool_name} timed out.")
            return None
        except Exception as e:
            logger.error(f"Pre-hook for {tool_name} failed: {e}")
            return None

    def run_post_hook(
        self, tool_name: str, tool_args: Dict[str, Any], tool_result: str
    ) -> Optional[str]:
        """
        Run the post-hook for a tool. Receives FORGE_TOOL_RESULT env var.
        Returns hook stdout if hook exists, else None.
        """
        hook_path = self._hook_path("post", tool_name)
        if not hook_path:
            return None

        extra = {"FORGE_TOOL_RESULT": tool_result, "FORGE_TOOL_NAME": tool_name}
        env = self._build_env(tool_args, extra)
        try:
            result = subprocess.run(
                self._get_executor(hook_path) + [hook_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.warning(
                    f"Post-hook for {tool_name} exited with {result.returncode}: {result.stderr}"
                )
            return result.stdout
        except subprocess.TimeoutExpired:
            logger.warning(f"Post-hook for {tool_name} timed out.")
            return None
        except Exception as e:
            logger.error(f"Post-hook for {tool_name} failed: {e}")
            return None

    @staticmethod
    def _get_executor(hook_path: str) -> list:
        """Returns the interpreter for a hook based on its extension."""
        ext = os.path.splitext(hook_path)[1].lower()
        if ext == ".py":
            return ["python"]
        if ext == ".ps1":
            return ["powershell", "-ExecutionPolicy", "Bypass", "-File"]
        # Default: bash/sh
        return ["bash"] if os.name != "nt" else ["cmd", "/c"]
