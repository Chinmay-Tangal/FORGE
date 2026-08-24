"""
forge/workspace/base.py — Abstract workspace interface.

All file and shell operations in Forge go through a Workspace subclass.
This ensures the agent is agnostic to whether it's running directly on the
host filesystem or inside a Docker sandbox.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Tuple


class Workspace(ABC):
    """Abstract base class for all workspace backends."""

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read a file and return its contents as a string."""

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """Write `content` to `path`, creating parent directories as needed."""

    @abstractmethod
    def run_command(self, command: str, cwd: str | None = None) -> Tuple[int, str]:
        """
        Execute a shell command.

        Returns
        -------
        (exit_code, combined_stdout_stderr)
        """
