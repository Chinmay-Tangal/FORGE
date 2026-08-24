# AGENTS.md — Forge Project Instructions for Forge

This file is auto-loaded by Forge when working inside its own codebase.

## Architecture Primer

Forge is an **event-sourced agentic coding assistant**.

### Core invariants
1. **Never mutate past events.** `ConversationState.events` is append-only. If you need to revise, append a corrective event.
2. **Every tool call must flow through `ToolRegistry`.** Do not call tool functions directly in agent code.
3. **Security before execution.** Every tool call must pass through `SecurityAnalyzer.requires_confirmation` before executing.
4. **Workspace abstraction.** All file and shell operations go through a `Workspace` subclass (`LocalWorkspace` or `DockerWorkspace`). Never use `open()` directly in tools.

### Module map
| Module | Responsibility |
|--------|---------------|
| `forge_core/events.py` | Pydantic event hierarchy (immutable) |
| `forge_core/state.py` | Mutable event log + metadata |
| `forge_core/agent.py` | LLM loop, tool dispatch, confirmation UX |
| `forge_core/llm.py` | LLMBackend (local), RouterLLM (local+frontier) |
| `forge_core/memory.py` | SQLite archival + recall memory |
| `forge_core/security.py` | Risk classification + confirmation policy |
| `forge_core/hooks.py` | Pre/post shell hooks |
| `forge_core/skills.py` | AGENTS.md + .md skill loading |
| `forge_core/condenser.py` | LLM-based context eviction |
| `forge_core/config.py` | TOML config loader |
| `forge_core/session.py` | JSONL session save/load |
| `forge_tools/registry.py` | Decorator-based tool registry |
| `forge_tools/builtin.py` | All built-in tools (read, write, shell, git, etc.) |
| `forge_workspace/` | Workspace interface + local/docker impls |
| `forge_cli/main.py` | Rich TUI, slash commands, streaming |
| `forge_eval/harness.py` | Real agent eval harness |

## Coding conventions
- All Pydantic models use `model_dump()` / `model_dump_json()` (v2 API). Never use `.dict()` or `.json()`.
- New tools: add to `forge_tools/builtin.py` using `@registry.register(...)`.
- New event types: add to `forge_core/events.py` and register in `forge_core/session.py:_EVENT_REGISTRY`.
- Never import `forge_cli` from `forge_core` — keep the dependency direction one-way.
- Use `logger = logging.getLogger(__name__)` in every module.

## Before committing
1. Run `python -m forge_eval.harness` and verify all tasks pass.
2. Do a manual smoke test: `forge --url http://localhost:8080/v1`.
3. Check that `CONTRIBUTING.md` is still accurate.
