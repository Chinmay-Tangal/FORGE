# Contributing to Forge

Forge follows an **event-sourced architecture** heavily inspired by the OpenHands Software Agent SDK (arXiv:2511.03690).

## Core Principles

1. **Event-Sourced State, One Source of Truth**
   Every action, observation, or message is an immutable `Event`. The only mutable state is `ConversationState`, which holds the event log. Do not modify past events; append new ones.

2. **Action-Execution-Observation Pattern**
   When adding a new tool:
   - Define the tool in `forge_tools/registry.py`.
   - The LLM proposes a `ToolCallAction`.
   - The system executes the tool and appends a `ToolResultObservation`.

3. **Opt-in Sandboxing**
   By default, operations use `LocalWorkspace` for speed. Any Docker-based sandboxing must implement the `Workspace` interface and be strictly opt-in.

4. **Security & Confirmation**
   All shell commands pass through `SecurityAnalyzer`. Do not bypass this. Small local models hallucinate more often than frontier models, making explicit confirmation essential.

5. **Run ForgeEval**
   Before submitting a PR that changes the prompt or agent loop, run the local eval harness:
   ```bash
   python -m forge_eval.harness
   ```
