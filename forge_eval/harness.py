"""
forge_eval/harness.py — Real eval harness for Forge.

Runs the agent against a set of tasks defined in tasks.json, asserts that
the expected tools were used, and produces a rich report + JSON results file.

Usage:
    python -m forge_eval.harness
    python -m forge_eval.harness --tasks forge_eval/tasks.json --url http://localhost:8080/v1
    python -m forge_eval.harness --filter t01,t02,t05
"""
import argparse
import json
import os
import sys
import time
import threading
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel

console = Console()
logging.basicConfig(level=logging.WARNING)


def _run_task_in_thread(
    task: Dict[str, Any],
    llm_url: str,
    result_container: List,
) -> None:
    """
    Runs one eval task inside a thread so we can enforce a timeout.
    Appends a result dict to result_container when done.
    """
    try:
        from forge_core.state import ConversationState
        from forge_core.events import Message, ToolCallAction
        from forge_core.llm import LLMBackend, RouterLLM
        from forge_core.security import SecurityAnalyzer
        from forge_core.agent import Agent
        from forge_tools.registry import ToolRegistry
        # Import builtin tools to populate a fresh registry
        import importlib, forge_tools.builtin as bt_module
        # Each task needs its own registry instance to avoid cross-contamination
        fresh_registry = bt_module.registry  # shared is OK since tools are stateless

        state = ConversationState()
        local_llm = LLMBackend(base_url=llm_url, model="qwen2.5-coder-7b")
        router = RouterLLM(local_llm=local_llm)
        security = SecurityAnalyzer(policy="auto")
        agent = Agent(state=state, llm=router, registry=fresh_registry, security=security)

        # Inject user message
        user_msg = Message(role="user", content=task["instruction"])
        state.append_event(user_msg)
        agent._last_user_message = task["instruction"]
        state.status = "active"

        t0 = time.time()
        events = list(agent.run())
        elapsed = time.time() - t0

        # Collect which tools were actually called
        tools_used = [
            e.tool_name for e in events if isinstance(e, ToolCallAction)
        ]

        # Check if all expected tools were used (at least once)
        expected = task.get("expected_tools", [])
        missing = [t for t in expected if t not in tools_used]
        passed = len(missing) == 0

        result_container.append({
            "id": task["id"],
            "name": task["name"],
            "passed": passed,
            "expected_tools": expected,
            "tools_used": tools_used,
            "missing_tools": missing,
            "elapsed_s": round(elapsed, 2),
            "error": None,
        })
    except Exception as e:
        result_container.append({
            "id": task["id"],
            "name": task["name"],
            "passed": False,
            "expected_tools": task.get("expected_tools", []),
            "tools_used": [],
            "missing_tools": task.get("expected_tools", []),
            "elapsed_s": 0.0,
            "error": str(e),
        })


def run_task(task: Dict[str, Any], llm_url: str) -> Dict[str, Any]:
    """Run a task with a per-task timeout. Returns the result dict."""
    timeout = task.get("timeout", 60)
    container: List[Dict] = []
    thread = threading.Thread(target=_run_task_in_thread, args=(task, llm_url, container), daemon=True)
    thread.start()
    thread.join(timeout=timeout + 5)  # 5s grace on top of task timeout

    if container:
        return container[0]
    # Timed out
    return {
        "id": task["id"],
        "name": task["name"],
        "passed": False,
        "expected_tools": task.get("expected_tools", []),
        "tools_used": [],
        "missing_tools": task.get("expected_tools", []),
        "elapsed_s": timeout,
        "error": f"TIMEOUT after {timeout}s",
    }


def main():
    parser = argparse.ArgumentParser(description="Forge Eval Harness")
    parser.add_argument("--tasks", default="forge_eval/tasks.json", help="Path to tasks JSON file")
    parser.add_argument("--url", default="http://localhost:8080/v1", help="LLM server URL")
    parser.add_argument("--filter", default="", help="Comma-separated task IDs to run (e.g. t01,t03)")
    args = parser.parse_args()

    # Load tasks
    tasks_path = args.tasks
    if not os.path.isfile(tasks_path):
        console.print(f"[red]Tasks file not found: {tasks_path}[/red]")
        sys.exit(1)
    with open(tasks_path, "r", encoding="utf-8") as f:
        all_tasks: List[Dict] = json.load(f)

    # Apply filter
    if args.filter:
        filter_ids = {t.strip() for t in args.filter.split(",")}
        tasks = [t for t in all_tasks if t["id"] in filter_ids]
    else:
        tasks = all_tasks

    # Check LLM health before running
    try:
        import httpx
        r = httpx.get(f"{args.url}/models", timeout=5.0)
        if r.status_code != 200:
            raise ValueError(f"Unexpected status {r.status_code}")
    except Exception as e:
        console.print(Panel(
            f"[bold yellow]⚠ LLM server unreachable at {args.url}[/bold yellow]\n"
            f"Error: {e}\n\n"
            "Start llama-server first, then re-run the harness.",
            title="Eval Skipped",
            border_style="yellow",
        ))
        sys.exit(0)

    console.print(Panel(
        f"Running [bold]{len(tasks)}[/bold] task(s) against [cyan]{args.url}[/cyan]",
        title="[bold]Forge Eval Harness[/bold]",
        border_style="blue",
    ))

    results: List[Dict] = []
    for task in tasks:
        console.print(f"  [dim]→[/dim] [{task['id']}] {task['name']} ...", end="")
        result = run_task(task, args.url)
        results.append(result)
        status = "[bold green]PASS[/bold green]" if result["passed"] else "[bold red]FAIL[/bold red]"
        console.print(f" {status} ({result['elapsed_s']}s)")
        if result.get("error"):
            console.print(f"    [red]Error: {result['error']}[/red]")
        if result["missing_tools"]:
            console.print(f"    [yellow]Missing tools: {result['missing_tools']}[/yellow]")

    # Summary table
    passed = sum(1 for r in results if r["passed"])
    table = Table(title="Eval Results", box=box.SIMPLE_HEAVY, show_lines=True)
    table.add_column("ID", style="dim", width=5)
    table.add_column("Task Name")
    table.add_column("Expected Tools", style="cyan")
    table.add_column("Used Tools", style="yellow")
    table.add_column("Time", justify="right")
    table.add_column("Result", justify="center")

    for r in results:
        status = "[bold green]PASS[/bold green]" if r["passed"] else "[bold red]FAIL[/bold red]"
        table.add_row(
            r["id"],
            r["name"],
            ", ".join(r["expected_tools"]),
            ", ".join(r["tools_used"]) or "[dim]none[/dim]",
            f"{r['elapsed_s']}s",
            status,
        )
    console.print(table)
    console.print(f"\n[bold]Result: {passed}/{len(results)} passed[/bold]")

    # Write JSON results
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join("forge_eval", f"results_{ts}.json")
    os.makedirs("forge_eval", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": ts,
            "url": args.url,
            "passed": passed,
            "total": len(results),
            "results": results,
        }, f, indent=2)
    console.print(f"[dim]Results written to {out_path}[/dim]")

    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
