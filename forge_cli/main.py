import os
import sys
import argparse
import logging
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.syntax import Syntax
from rich.text import Text
from rich import box

from forge_core.config import Config
from forge_core.state import ConversationState
from forge_core.events import Message, ToolCallAction, ToolResultObservation
from forge_core.llm import LLMBackend, RouterLLM
from forge_core.security import SecurityAnalyzer
from forge_core.agent import Agent, ConfirmationRequiredEvent
from forge_core.session import SessionManager, generate_session_id
from forge_core.memory import MemoryStore
from forge_tools.builtin import registry

console = Console()

FORGE_BANNER = """
[bold blue]
  ███████╗ ██████╗ ██████╗  ██████╗ ███████╗
  ██╔════╝██╔═══██╗██╔══██╗██╔════╝ ██╔════╝
  █████╗  ██║   ██║██████╔╝██║  ███╗█████╗  
  ██╔══╝  ██║   ██║██╔══██╗██║   ██║██╔══╝  
  ██║     ╚██████╔╝██║  ██║╚██████╔╝███████╗
  ╚═╝      ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝
[/bold blue]
  [dim]Terminal-native local agentic coding assistant[/dim]
"""

SLASH_COMMANDS = {
    "/help":     "Show this help message.",
    "/history":  "Show the last 10 events from the session.",
    "/memory":   "/memory <query>  — Search archival memory.",
    "/sessions": "List available saved sessions.",
    "/resume":   "/resume <session-id>  — Load a different session.",
    "/policy":   "/policy strict|auto  — Change security policy.",
    "/skills":   "Reload skills from disk and show count.",
    "/frontier": "Toggle: route next turn to frontier model.",
    "/clear":    "Clear the working context summary.",
    "/status":   "Show current session status, event count, cost.",
}


def _render_assistant_response(content: str) -> None:
    """Render assistant text, detecting fenced code blocks for syntax highlighting."""
    import re
    pattern = re.compile(r"```(\w+)?\n(.*?)```", re.DOTALL)
    last_end = 0
    for m in pattern.finditer(content):
        # Print text before the code block
        before = content[last_end:m.start()].strip()
        if before:
            console.print(f"[green]{before}[/green]")
        lang = m.group(1) or "text"
        code = m.group(2)
        console.print(Syntax(code, lang, theme="monokai", line_numbers=False))
        last_end = m.end()
    # Remaining text
    after = content[last_end:].strip()
    if after:
        console.print(f"[green]{after}[/green]")


def handle_slash_command(
    cmd: str,
    state: ConversationState,
    agent: Agent,
    session_manager: SessionManager,
    session_id: str,
    security: SecurityAnalyzer,
) -> Optional[bool]:
    """
    Handle a slash command. Returns True to continue the loop, None to do nothing.
    """
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if command == "/help":
        table = Table(title="Forge Slash Commands", box=box.SIMPLE)
        table.add_column("Command", style="bold cyan")
        table.add_column("Description")
        for c, desc in SLASH_COMMANDS.items():
            table.add_row(c, desc)
        console.print(table)

    elif command == "/history":
        table = Table(title="Recent Events", box=box.SIMPLE, show_lines=True)
        table.add_column("#", style="dim")
        table.add_column("Type", style="bold")
        table.add_column("Summary")
        for i, event in enumerate(state.events[-10:]):
            etype = type(event).__name__
            if isinstance(event, Message):
                summary = f"[{event.role}] {event.content[:80]}"
            elif isinstance(event, ToolCallAction):
                summary = f"{event.tool_name}({str(event.tool_args)[:60]})"
            elif isinstance(event, ToolResultObservation):
                status = "✓" if event.success else "✗"
                summary = f"{status} {event.content[:80]}"
            else:
                summary = str(event.model_dump())[:80]
            table.add_row(str(i + 1), etype, summary)
        console.print(table)

    elif command == "/memory":
        if not arg:
            console.print("[yellow]Usage: /memory <query>[/yellow]")
        else:
            store = MemoryStore()
            results = store.search_archival(arg)
            if not results:
                console.print("[dim]No memory results found.[/dim]")
            else:
                for r in results:
                    console.print(f"  [cyan][{r['id']}][/cyan] {r['timestamp']}: {r['content']}")

    elif command == "/sessions":
        sessions = session_manager.list()
        if not sessions:
            console.print("[dim]No saved sessions found.[/dim]")
        else:
            table = Table(title="Saved Sessions", box=box.SIMPLE)
            table.add_column("Session ID", style="cyan")
            table.add_column("Saved At")
            table.add_column("Events", justify="right")
            table.add_column("Status")
            for s in sessions:
                table.add_row(s["session_id"], s.get("saved_at", "")[:19], str(s["event_count"]), s["status"])
            console.print(table)

    elif command == "/resume":
        if not arg:
            console.print("[yellow]Usage: /resume <session-id>[/yellow]")
        else:
            try:
                new_state = session_manager.load(arg)
                state.events = new_state.events
                state.status = new_state.status
                state.working_context = new_state.working_context
                state.cost = new_state.cost
                console.print(f"[green]Resumed session '{arg}' ({len(state.events)} events).[/green]")
            except FileNotFoundError:
                console.print(f"[red]Session '{arg}' not found.[/red]")

    elif command == "/policy":
        if arg in ("strict", "auto"):
            security.policy = arg
            console.print(f"[green]Security policy set to '{arg}'.[/green]")
        else:
            console.print("[yellow]Usage: /policy strict|auto[/yellow]")

    elif command == "/skills":
        agent.skill_loader.reload()
        count = len(agent.skill_loader._skills)
        console.print(f"[green]Skills reloaded. {count} skill(s) loaded.[/green]")

    elif command == "/frontier":
        return "toggle_frontier"

    elif command == "/clear":
        state.working_context = ""
        console.print("[green]Working context cleared.[/green]")

    elif command == "/status":
        console.print(
            f"  Session: [cyan]{session_id}[/cyan]\n"
            f"  Status:  [yellow]{state.status}[/yellow]\n"
            f"  Events:  {len(state.events)}\n"
            f"  Cost:    ${state.cost:.4f}\n"
            f"  Working context: {len(state.working_context)} chars"
        )

    else:
        console.print(f"[red]Unknown command '{command}'. Type /help for help.[/red]")

    return True


def main():
    parser = argparse.ArgumentParser(description="Forge — Local Agentic Coding Assistant")
    parser.add_argument("--model", type=str, default=None, help="Local model name")
    parser.add_argument("--url", type=str, default=None, help="Llama.cpp server URL")
    parser.add_argument("--policy", type=str, default=None, choices=["auto", "strict"])
    parser.add_argument("--workspace", type=str, default="local", choices=["local", "docker"])
    parser.add_argument("--session", type=str, default=None, help="Resume a session ID")
    parser.add_argument("--frontier-url", type=str, default=None)
    parser.add_argument("--frontier-model", type=str, default=None)
    parser.add_argument("--frontier-key", type=str, default=None)
    parser.add_argument("--config", type=str, default=".forge/config.toml")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    # Load config, CLI args override config file
    cfg = Config.load(args.config)
    if args.url:
        cfg.local_llm_url = args.url
    if args.model:
        cfg.local_model = args.model
    if args.policy:
        cfg.security_policy = args.policy
    if args.frontier_url:
        cfg.frontier_llm_url = args.frontier_url
    if args.frontier_model:
        cfg.frontier_model = args.frontier_model
    if args.frontier_key:
        cfg.frontier_api_key = args.frontier_key

    # --- Print banner ---
    console.print(FORGE_BANNER)

    # --- Build LLM stack ---
    local_llm = LLMBackend(base_url=cfg.local_llm_url, model=cfg.local_model)
    frontier_llm = None
    if cfg.frontier_llm_url and cfg.frontier_model:
        import httpx
        frontier_client = LLMBackend(base_url=cfg.frontier_llm_url, model=cfg.frontier_model)
        if cfg.frontier_api_key:
            frontier_client.client = httpx.Client(
                timeout=120.0,
                headers={"Authorization": f"Bearer {cfg.frontier_api_key}"},
            )
        frontier_llm = frontier_client

    router_llm = RouterLLM(local_llm=local_llm, frontier_llm=frontier_llm)
    security = SecurityAnalyzer(policy=cfg.security_policy)

    # --- Session setup ---
    session_manager = SessionManager(sessions_dir=cfg.sessions_dir)
    if args.session:
        try:
            state = session_manager.load(args.session)
            session_id = args.session
            console.print(f"[green]Resumed session:[/green] {session_id} ({len(state.events)} events)")
        except FileNotFoundError:
            console.print(f"[red]Session '{args.session}' not found. Starting fresh.[/red]")
            state = ConversationState()
            session_id = generate_session_id()
    else:
        state = ConversationState()
        session_id = generate_session_id()

    agent = Agent(state=state, llm=router_llm, registry=registry, security=security, config=cfg)

    # --- Print startup info ---
    console.print(Panel(
        f"[bold]Session:[/bold] {session_id}\n"
        f"[bold]LLM:[/bold]     {cfg.local_llm_url}  ({cfg.local_model})\n"
        f"[bold]Workspace:[/bold] {args.workspace}\n"
        f"[bold]Policy:[/bold]  {cfg.security_policy}",
        title="Forge Ready",
        border_style="blue",
    ))

    # Health check
    if not local_llm.check_health():
        console.print(
            f"[bold yellow]⚠ Warning:[/bold yellow] Cannot reach LLM at {cfg.local_llm_url}. "
            "Start llama-server first."
        )

    console.print("Type your request, or [bold]/help[/bold] for commands. [dim]Ctrl+C to interrupt, Ctrl+D to exit.[/dim]\n")

    # --- Prompt session with history ---
    history_path = os.path.join(cfg.sessions_dir, ".prompt_history")
    os.makedirs(os.path.dirname(history_path), exist_ok=True)
    session = PromptSession(
        history=FileHistory(history_path),
        auto_suggest=AutoSuggestFromHistory(),
    )

    require_frontier = False  # toggleable via /frontier

    while True:
        try:
            with patch_stdout():
                user_input = session.prompt(
                    f"[{session_id[:8]}] > ",
                )
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted. Type 'exit' to quit.[/dim]")
            continue
        except EOFError:
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Exit
        if user_input.lower() in ("exit", "quit", "q"):
            session_manager.save(state, session_id)
            console.print(f"[dim]Session saved: {session_id}[/dim]")
            break

        # Slash commands
        if user_input.startswith("/"):
            result = handle_slash_command(user_input, state, agent, session_manager, session_id, security)
            if result == "toggle_frontier":
                require_frontier = not require_frontier
                label = "[bold magenta]ON[/bold magenta]" if require_frontier else "[dim]OFF[/dim]"
                console.print(f"Frontier routing: {label}")
            session_manager.save(state, session_id)
            continue

        # Normal user message
        state.append_event(Message(role="user", content=user_input))
        agent._last_user_message = user_input
        state.status = "active"

        # --- Run agent with streaming ---
        with console.status("[bold green]Thinking...[/bold green]", spinner="dots"):
            try:
                events = list(agent.run(require_frontier=require_frontier))
            except Exception as e:
                console.print(f"[bold red]Agent error:[/bold red] {e}")
                events = []

        # After non-streaming run, check if paused for confirmation
        if state.status == "paused" and agent._pending_confirmation:
            # Find the ConfirmationRequiredEvent
            conf_events = [e for e in events if isinstance(e, ConfirmationRequiredEvent)]
            if conf_events:
                ce = conf_events[-1]
                console.print(Panel(
                    f"[bold yellow]⚠ Confirmation Required[/bold yellow]\n\n"
                    f"Tool:   [cyan]{ce.tool_name}[/cyan]\n"
                    f"Args:   {ce.tool_args}\n"
                    f"Risk:   [red]{ce.risk}[/red]",
                    border_style="yellow",
                ))
                try:
                    with patch_stdout():
                        answer = session.prompt("Proceed? [y/N]: ")
                    if answer.strip().lower() == "y":
                        for evt in agent.resume_confirmed():
                            _display_event(evt)
                    else:
                        for evt in agent.resume_denied():
                            _display_event(evt)
                except (KeyboardInterrupt, EOFError):
                    for evt in agent.resume_denied():
                        _display_event(evt)
        else:
            # Display all collected events
            for event in events:
                _display_event(event)

        # Reset frontier toggle after one turn
        if require_frontier:
            require_frontier = False
            console.print("[dim](Frontier toggle reset to OFF)[/dim]")

        # Auto-save session after every turn
        session_manager.save(state, session_id)

    console.print("[bold blue]Goodbye.[/bold blue]")


def _display_event(event) -> None:
    """Render a single event to the terminal."""
    if isinstance(event, Message):
        if event.role == "assistant":
            console.print(Panel(
                Text.from_markup(f"[green]{event.content}[/green]"),
                title="[bold green]Forge[/bold green]",
                border_style="green",
                padding=(0, 1),
            ))
        elif event.role == "system":
            console.print(f"[bold dim]System:[/bold dim] {event.content}")
    elif isinstance(event, ToolCallAction):
        console.print(f"  [bold yellow]→ {event.tool_name}[/bold yellow]({str(event.tool_args)[:100]})")
    elif isinstance(event, ToolResultObservation):
        color = "cyan" if event.success else "red"
        icon = "✓" if event.success else "✗"
        preview = event.content[:300] + ("..." if len(event.content) > 300 else "")
        console.print(f"  [{color}]{icon} {event.tool_name}:[/{color}] {preview}")
    elif isinstance(event, ConfirmationRequiredEvent):
        pass  # handled separately above


if __name__ == "__main__":
    main()
