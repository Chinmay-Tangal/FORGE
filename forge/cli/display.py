"""
forge/cli/display.py — Rich rendering helpers for the Forge TUI.

Centralises all terminal output so that main.py stays focused on the
REPL loop and commands.py stays focused on slash-command logic.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

if TYPE_CHECKING:
    from forge.core.events import Event

console = Console()

_FENCE_RE = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)

FORGE_TITLE = "[bold #ff9e3b]Forge[/bold #ff9e3b]"
FORGE_LOGO = "[bold #ff9e3b]FORGE[/bold #ff9e3b]"

FORGE_BANNER = r"""
  [bold #ff7700]███████╗ ██████╗ ██████╗  ██████╗ ███████╗[/bold #ff7700]
  [bold #ff8800]██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝[/bold #ff8800]
  [bold #ff9900]█████╗  ██║   ██║██████╔╝██║  ███╗█████╗  [/bold #ff9900]
  [bold #ffaa00]██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  [/bold #ffaa00]
  [bold #ffbb00]██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗[/bold #ffbb00]
  [bold #ffcc00]╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝[/bold #ffcc00]
  [dim]Terminal-native local agentic coding assistant[/dim]
"""


def print_banner() -> None:
    console.print(FORGE_BANNER)


def render_assistant(content: str) -> None:
    """Render assistant text cleanly inside a styled Rich Panel."""
    content = content.strip()
    if not content:
        return
    from rich.markdown import Markdown
    md = Markdown(content, code_theme="monokai")
    console.print(Panel(md, title=f" {FORGE_TITLE} ", border_style="#ff9e3b", padding=(0, 2)))


def render_tool_call(tool_name: str, tool_args: dict) -> None:
    args_str = str(tool_args)
    if len(args_str) > 120:
        args_str = args_str[:120] + "…"
    console.print(f"  [bold yellow]→ {tool_name}[/bold yellow]({args_str})")


def render_tool_result(tool_name: str, content: str, success: bool) -> None:
    icon = "[green]✓[/green]" if success else "[red]✗[/red]"
    preview = content[:400] + ("…" if len(content) > 400 else "")
    console.print(f"  {icon} [dim]{tool_name}:[/dim] {preview}")


def render_confirmation_prompt(tool_name: str, tool_args: dict, risk: str) -> None:
    console.print(Panel(
        f"[bold yellow]Tool:[/bold yellow]  {tool_name}\n"
        f"[bold yellow]Args:[/bold yellow]  {tool_args}\n"
        f"[bold yellow]Risk:[/bold yellow]  [red]{risk.upper()}[/red]",
        title="[bold red]⚠  Confirmation Required[/bold red]",
        border_style="red",
    ))


def render_event(event: "Event") -> None:
    """Dispatch rendering for any event type."""
    from forge.core.events import (
        ConfirmationRequiredEvent,
        Message,
        ToolCallAction,
        ToolResultObservation,
    )

    if isinstance(event, Message):
        if event.role == "assistant":
            render_assistant(event.content)
        elif event.role == "system":
            console.print(f"[dim]System: {event.content}[/dim]")
    elif isinstance(event, ToolCallAction):
        render_tool_call(event.tool_name, event.tool_args)
    elif isinstance(event, ToolResultObservation):
        render_tool_result(event.tool_name, event.content, event.success)
    elif isinstance(event, ConfirmationRequiredEvent):
        pass  # handled interactively in main.py
