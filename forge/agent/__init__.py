"""
forge.agent — Agentic execution loop.

Public re-exports for backward compatibility:

    from forge.agent import Agent
    from forge.core.events import ConfirmationRequiredEvent
"""
from forge.agent.loop import Agent
from forge.core.events import ConfirmationRequiredEvent

__all__ = ["Agent", "ConfirmationRequiredEvent"]
