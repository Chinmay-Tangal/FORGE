"""
forge/core/state.py — Mutable conversation state container.

ConversationState is the single mutable object in the system.
Its `events` list is append-only by convention — never remove or modify
past events; instead append corrective events.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from forge.core.events import Action, Event, Message, Observation

logger = logging.getLogger(__name__)


class ConversationState(BaseModel):
    """
    Holds the immutable event log plus a small amount of mutable metadata.

    Fields
    ------
    events : List[Event]
        Append-only event log. All agent actions, tool results and messages
        live here in chronological order.
    status : str
        Current lifecycle status: 'active' | 'paused' | 'finished' | 'error'.
    cost : float
        Accumulated estimated token cost (USD) for this session.
    confirmation_policy : str
        Security policy in effect: 'auto' | 'strict'.
    working_context : str
        MemGPT-style mutable working memory. Updated by the condenser when
        old events are evicted from the in-context window.
    """

    events: List[Event] = Field(default_factory=list)
    status: str = "active"
    cost: float = 0.0
    confirmation_policy: str = "auto"
    working_context: str = ""

    def append_event(self, event: Event) -> None:
        """Append an event to the log. The only permitted write to `events`."""
        self.events.append(event)

    def get_recent_messages(self, limit: int = 20) -> List[Message]:
        """Return the most recent `limit` Message events."""
        return [e for e in self.events if isinstance(e, Message)][-limit:]

    def get_all_events(self) -> List[Event]:
        return list(self.events)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
