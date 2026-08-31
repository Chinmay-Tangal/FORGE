"""
forge/cli/main.py — Forge REPL entry point.

Responsibilities (only):
  - Parse CLI arguments
  - Build the agent and its dependencies from Config
  - Manage the prompt-toolkit REPL loop
  - Delegate slash commands to forge.cli.commands
  - Delegate rendering to forge.cli.display
  - Save the session after every turn

Usage::

    forge --url http://localhost:8080/v1
    forge --session 20260824-155351-7bce8870
    forge --policy strict --frontier-url https://api.openai.com/v1 --frontier-model gpt-4o
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout
from rich.panel import Panel

from forge.agent import Agent, ConfirmationRequiredEvent
from forge.cli import commands as cmd_module
from forge.cli.commands import TOGGLE_FRONTIER
from forge.cli.display import console, print_banner, render_confirmation_prompt, render_event
from forge.config import Config
from forge.core.events import Message
from forge.core.state import ConversationState
from forge.llm.backend import LLMBackend
from forge.llm.router import RouterLLM
from forge.security.analyzer import SecurityAnalyzer
from forge.session import SessionManager, generate_session_id
from forge.tools import registry


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge",
        description="Forge — Terminal-native local agentic coding assistant.",
    )
    p.add_argument("--url", metavar="URL", default=None,
                   help="Local LLM server base URL (default: http://localhost:8080/v1).")
    p.add_argument("--model", metavar="MODEL", default=None,
                   help="Local model identifier.")
    p.add_argument("--policy", choices=["auto", "strict"], default=None,
                   help="Security confirmation policy.")
    p.add_argument("--workspace", choices=["local", "docker"], default="local",
                   help="Workspace backend (default: local).")
    p.add_argument("--session", metavar="ID", default=None,
                   help="Resume an existing session by ID.")
    p.add_argument("--frontier-url", metavar="URL", default=None,
                   help="Frontier LLM base URL (e.g. https://api.openai.com/v1).")
    p.add_argument("--frontier-model", metavar="MODEL", default=None)
    p.add_argument("--frontier-key", metavar="KEY", default=None,
                   help="Frontier API key. Also read from FORGE_FRONTIER_KEY env var.")
    p.add_argument("--config", metavar="FILE", default=".forge/config.toml",
                   help="Path to config TOML file.")
    p.add_argument("--dump-config", action="store_true",
                   help="Print effective config and exit.")
    p.add_argument("--verbose", action="store_true",
                   help="Enable DEBUG logging.")
    return p


def main() -> None:  # noqa: C901 (complexity is intentional — this is a REPL)
    args = _build_arg_parser().parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Config (file → CLI overrides)
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

    if args.dump_config:
        from dataclasses import asdict
        for k, v in asdict(cfg).items():
            console.print(f"  {k} = {v!r}")
        sys.exit(0)

    # LLM stack
    local_llm = LLMBackend(base_url=cfg.local_llm_url, model=cfg.local_model)
    frontier_llm: LLMBackend | None = None
    if cfg.frontier_llm_url and cfg.frontier_model:
        import httpx
        frontier_llm = LLMBackend(base_url=cfg.frontier_llm_url, model=cfg.frontier_model)
        if cfg.frontier_api_key:
            frontier_llm.client = httpx.Client(
                timeout=120.0,
                headers={"Authorization": f"Bearer {cfg.frontier_api_key}"},
            )
    router = RouterLLM(local_llm=local_llm, frontier_llm=frontier_llm)
    security = SecurityAnalyzer(policy=cfg.security_policy)

    # Session
    session_manager = SessionManager(sessions_dir=cfg.sessions_dir)
    if args.session:
        try:
            state = session_manager.load(args.session)
            session_id = args.session
        except FileNotFoundError:
            console.print(f"[red]Session '{args.session}' not found — starting fresh.[/red]")
            state = ConversationState()
            session_id = generate_session_id()
    else:
        state = ConversationState()
        session_id = generate_session_id()

    agent = Agent(state=state, llm=router, registry=registry, security=security, config=cfg)

    # Startup output
    print_banner()
    from forge.workspace.grounding import get_git_info
    git_info = get_git_info(os.getcwd())
    repo_branch = f"  ({git_info['branch']})" if git_info.get("is_repo") and git_info.get("branch") else ""
    proj_name = git_info.get("repo_name") or os.path.basename(os.getcwd())

    console.print(Panel(
        f"[bold]Session :[/bold] {session_id}\n"
        f"[bold]LLM     :[/bold] {cfg.local_llm_url}  ([dim]{cfg.local_model}[/dim])\n"
        f"[bold]Project :[/bold] {proj_name}{repo_branch}\n"
        f"[bold]Workspace:[/bold] {args.workspace}  ([dim]{os.getcwd()}[/dim])\n"
        f"[bold]Policy  :[/bold] {cfg.security_policy}\n"
        f"[bold]Tools   :[/bold] {len(registry)} registered",
        title="[bold blue]Forge[/bold blue]",
        border_style="blue",
    ))

    if not local_llm.check_health():
        console.print(
            f"[bold yellow]⚠  LLM unreachable at {cfg.local_llm_url}.[/bold yellow]  "
            "Start llama-server first."
        )

    console.print(
        "Type your request, or [bold cyan]/help[/bold cyan] for commands. "
        "[dim]Ctrl-C to interrupt · Ctrl-D / 'exit' to quit.[/dim]\n"
    )

    # Prompt-toolkit session (with history)
    os.makedirs(cfg.sessions_dir, exist_ok=True)
    history_file = os.path.join(cfg.sessions_dir, ".prompt_history")
    prompt_session: PromptSession = PromptSession(
        history=FileHistory(history_file),
        auto_suggest=AutoSuggestFromHistory(),
    )
    require_frontier = False

    # REPL loop
    while True:
        try:
            with patch_stdout():
                user_input = prompt_session.prompt(f"[{session_id[:8]}] > ")
        except KeyboardInterrupt:
            console.print("\n[dim]Interrupted.[/dim]")
            continue
        except EOFError:
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Exit
        if user_input.lower() in ("exit", "quit", "q"):
            break

        # Slash commands
        if user_input.startswith("/"):
            result = cmd_module.handle(
                user_input,
                state=state,
                agent=agent,
                session_manager=session_manager,
                session_id=session_id,
                security=security,
            )
            if result == TOGGLE_FRONTIER:
                require_frontier = not require_frontier
                label = "[bold magenta]ON[/bold magenta]" if require_frontier else "[dim]OFF[/dim]"
                console.print(f"Frontier routing: {label}")
            session_manager.save(state, session_id)
            continue

        # Regular user turn
        state.append_event(Message(role="user", content=user_input))
        agent._last_user_message = user_input
        state.status = "active"

        # Run agent loop with live event rendering
        events = []
        with console.status("[bold green]Thinking…[/bold green]", spinner="dots"):
            try:
                for event in agent.run(require_frontier=require_frontier):
                    events.append(event)
                    if not isinstance(event, Message):
                        render_event(event)
            except Exception as exc:
                console.print(f"[bold red]Agent error:[/bold red] {exc}")

        # Confirmation UX
        if state.status == "paused" and agent._pending:
            conf_evts = [e for e in events if isinstance(e, ConfirmationRequiredEvent)]
            if conf_evts:
                ce = conf_evts[-1]
                render_confirmation_prompt(ce.tool_name, ce.tool_args, ce.risk)
                try:
                    with patch_stdout():
                        answer = prompt_session.prompt("Proceed? [y/N]: ")
                    if answer.strip().lower() == "y":
                        for evt in agent.resume_confirmed():
                            render_event(evt)
                    else:
                        for evt in agent.resume_denied():
                            render_event(evt)
                except (KeyboardInterrupt, EOFError):
                    for evt in agent.resume_denied():
                        render_event(evt)
        else:
            for event in events:
                if isinstance(event, Message):
                    render_event(event)

        # Reset frontier toggle after one turn
        if require_frontier:
            require_frontier = False
            console.print("[dim](Frontier routing reset to OFF)[/dim]")

        session_manager.save(state, session_id)

    # Graceful exit
    session_manager.save(state, session_id)
    console.print(f"\n[dim]Session saved: {session_id}[/dim]")
    console.print("[bold blue]Goodbye.[/bold blue]")


if __name__ == "__main__":
    main()
