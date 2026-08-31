"""
forge/cli/commands.py — Slash command handlers for the Forge REPL.

Each ``handle_*`` function takes the components it needs and performs the
appropriate action, printing output to the shared ``console``. Handlers
return a sentinel string or None to signal special behaviour to main.py.

Available commands:
    /help      /history   /memory    /sessions  /resume
    /policy    /skills    /frontier  /clear     /status
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from rich import box
from rich.table import Table

from forge.cli.display import FORGE_TITLE, console

if TYPE_CHECKING:
    from forge.agent import Agent
    from forge.core.state import ConversationState
    from forge.security.analyzer import SecurityAnalyzer
    from forge.session import SessionManager

logger = logging.getLogger(__name__)

# Sentinel returned when the /frontier command is processed
TOGGLE_FRONTIER = "__toggle_frontier__"

HELP_TEXT = {
    "/help":     "Show this help message.",
    "/history":  "Show the last 10 session events.",
    "/memory":   "/memory <query>  — Search archival memory.",
    "/sessions": "List all saved sessions.",
    "/resume":   "/resume <id>     — Switch to a saved session.",
    "/policy":   "/policy strict|auto  — Change security policy.",
    "/skills":   "Reload skills from disk.",
    "/frontier": "Toggle frontier model routing for the next turn.",
    "/clear":    "Clear the working-context summary.",
    "/status":   "Show session status, event count, and cost.",
}


def handle(
    raw: str,
    *,
    state: "ConversationState",
    agent: "Agent",
    session_manager: "SessionManager",
    session_id: str,
    security: "SecurityAnalyzer",
) -> Optional[str]:
    """
    Dispatch a slash command.

    Returns
    -------
    ``TOGGLE_FRONTIER`` if the /frontier command was issued, otherwise ``None``.
    """
    parts = raw.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/help":
        _help()
    elif cmd == "/history":
        _history(state)
    elif cmd == "/memory":
        _memory(arg)
    elif cmd == "/sessions":
        _sessions(session_manager)
    elif cmd == "/resume":
        _resume(arg, state=state, session_manager=session_manager)
    elif cmd == "/policy":
        _policy(arg, security=security)
    elif cmd == "/skills":
        _skills(agent)
    elif cmd == "/frontier":
        return TOGGLE_FRONTIER
    elif cmd == "/clear":
        state.working_context = ""
        console.print("[green]Working context cleared.[/green]")
    elif cmd == "/status":
        _status(state, session_id)
    else:
        console.print(f"[red]Unknown command '{cmd}'. Type /help for help.[/red]")
    return None

# Individual handlers
def _help() -> None:
    table = Table(title=f"{FORGE_TITLE} Slash Commands", box=box.SIMPLE, show_header=True)
    table.add_column("Command", style="bold cyan", no_wrap=True)
    table.add_column("Description")
    for cmd, desc in HELP_TEXT.items():
        table.add_row(cmd, desc)
    console.print(table)


def _history(state: "ConversationState") -> None:
    from forge.core.events import Message, ToolCallAction, ToolResultObservation

    table = Table(title="Recent Events (last 10)", box=box.SIMPLE, show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Type", style="bold")
    table.add_column("Summary")

    for i, evt in enumerate(state.events[-10:], 1):
        etype = type(evt).__name__
        if isinstance(evt, Message):
            summary = f"[{evt.role}] {evt.content[:90]}"
        elif isinstance(evt, ToolCallAction):
            summary = f"{evt.tool_name}({str(evt.tool_args)[:70]})"
        elif isinstance(evt, ToolResultObservation):
            summary = ("✓ " if evt.success else "✗ ") + evt.content[:80]
        else:
            summary = str(evt.model_dump())[:80]
        table.add_row(str(i), etype, summary)
    console.print(table)


def _memory(query: str) -> None:
    if not query:
        console.print("[yellow]Usage: /memory <query>[/yellow]")
        return
    from forge.memory.store import MemoryStore
    results = MemoryStore().search_archival(query)
    if not results:
        console.print("[dim]No matching memories.[/dim]")
    else:
        for r in results:
            console.print(f"  [cyan][#{r['id']}][/cyan] {r['timestamp'][:19]}  {r['content']}")


def _sessions(session_manager: "SessionManager") -> None:
    sessions = session_manager.list()
    if not sessions:
        console.print("[dim]No saved sessions found.[/dim]")
        return
    table = Table(title="Saved Sessions", box=box.SIMPLE)
    table.add_column("Session ID", style="cyan")
    table.add_column("Saved At")
    table.add_column("Events", justify="right")
    table.add_column("Status")
    for s in sessions:
        table.add_row(
            s["session_id"],
            s.get("saved_at", "")[:19],
            str(s["event_count"]),
            s["status"],
        )
    console.print(table)


def _resume(
    session_id: str,
    *,
    state: "ConversationState",
    session_manager: "SessionManager",
) -> None:
    if not session_id:
        console.print("[yellow]Usage: /resume <session-id>[/yellow]")
        return
    try:
        loaded = session_manager.load(session_id)
        state.events = loaded.events
        state.status = loaded.status
        state.working_context = loaded.working_context
        state.cost = loaded.cost
        console.print(f"[green]Resumed '{session_id}' ({len(state.events)} events).[/green]")
    except FileNotFoundError:
        console.print(f"[red]Session '{session_id}' not found.[/red]")


def _policy(arg: str, *, security: "SecurityAnalyzer") -> None:
    if arg not in ("strict", "auto"):
        console.print("[yellow]Usage: /policy strict|auto[/yellow]")
        return
    security.policy = arg
    console.print(f"[green]Security policy → '{arg}'.[/green]")


def _skills(agent: "Agent") -> None:
    agent.skill_loader.reload()
    n = len(agent.skill_loader._skills)
    console.print(f"[green]Skills reloaded — {n} skill(s) active.[/green]")


def _status(state: "ConversationState", session_id: str) -> None:
    console.print(
        f"  Session : [cyan]{session_id}[/cyan]\n"
        f"  Status  : [yellow]{state.status}[/yellow]\n"
        f"  Events  : {len(state.events)}\n"
        f"  Cost    : ${state.cost:.4f}\n"
        f"  Context : {len(state.working_context)} chars"
    )
