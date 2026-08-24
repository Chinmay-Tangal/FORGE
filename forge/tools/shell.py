"""
forge/tools/shell.py — Shell execution tool.

Registered tools: shell
"""
from __future__ import annotations

import os

from forge.tools import registry
from forge.workspace.local import LocalWorkspace

_ws = LocalWorkspace(os.getcwd())


@registry.register(
    name="shell",
    description=(
        "Run an arbitrary shell command in the workspace. "
        "High-risk commands (rm, sudo, etc.) require user confirmation. "
        "Prefer specialised tools (git_*, read_file, etc.) over raw shell where possible."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "cwd": {
                "type": "string",
                "description": "Optional working directory relative to workspace root.",
            },
        },
        "required": ["command"],
    },
)
def shell(command: str, cwd: str | None = None) -> str:
    exit_code, output = _ws.run_command(command, cwd)
    if exit_code == 0:
        return f"Exit 0:\n{output}" if output.strip() else "Command completed with no output."
    return f"Exit {exit_code}:\n{output}"
