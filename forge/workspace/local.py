"""
forge/workspace/local.py — Local filesystem workspace.

Executes file operations and shell commands directly on the host machine.
This is the default workspace — zero overhead, no containerisation.
"""
from __future__ import annotations

import logging
import os
import subprocess
from typing import Tuple

from forge.workspace.base import Workspace

logger = logging.getLogger(__name__)


class LocalWorkspace(Workspace):
    """
    In-process workspace backed by the host filesystem.

    All paths passed to public methods are resolved relative to `base_dir`.
    Absolute paths that escape `base_dir` are permitted — this is an
    intentional design choice for the trusted-local-execution model.
    """

    def __init__(self, base_dir: str) -> None:
        self.base_dir = os.path.abspath(base_dir)

    def _resolve(self, path: str) -> str:
        """Resolve a relative or absolute path against base_dir, handling POSIX/Windows paths."""
        if not path:
            return self.base_dir
        path = str(path).strip().strip("'\"")
        if not path or path == ".":
            return self.base_dir

        import re
        # Handle Git Bash / MSYS style drive paths like /d/... or /c/...
        m = re.match(r"^/([a-zA-Z])/(.*)", path)
        if m and os.name == "nt":
            drive, rest = m.groups()
            path = f"{drive.upper()}:/{rest}"

        if os.path.isabs(path):
            return os.path.abspath(path)
        return os.path.abspath(os.path.join(self.base_dir, path))

    def read_file(self, path: str) -> str:
        resolved = self._resolve(path)
        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def write_file(self, path: str, content: str) -> None:
        resolved = self._resolve(path)
        os.makedirs(os.path.dirname(resolved) or ".", exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(content)

    def run_command(self, command: str, cwd: str | None = None) -> Tuple[int, str]:
        run_dir = self._resolve(cwd) if cwd else self.base_dir
        cmd_stripped = command.strip()

        # Handle simple 'cd <path>' or 'cd' command to persistently change workspace working directory
        if cmd_stripped == "cd" or cmd_stripped.startswith("cd "):
            target = cmd_stripped[3:].strip().strip("'\"") if len(cmd_stripped) > 3 else ""
            new_dir = self._resolve(target) if target else os.path.expanduser("~")
            if os.path.isdir(new_dir):
                self.base_dir = os.path.abspath(new_dir)
                try:
                    os.chdir(self.base_dir)
                except Exception:
                    pass
                return 0, f"Working directory changed to: {self.base_dir}"
            else:
                return 1, f"cd: directory not found: {target}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=run_dir,
                capture_output=True,
                text=True,
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return result.returncode, output
        except Exception as exc:
            return 1, str(exc)
