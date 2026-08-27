"""
forge/core/events.py — Immutable event hierarchy.

Every action, observation, and message in the system is represented as an
immutable Pydantic model that gets appended to ConversationState.events.
Never mutate existing events — always append new ones.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base class for every event in the event-sourced system."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = "agent"  # 'agent' | 'user' | 'system'

    model_config = {"frozen": False}  # state is append-only, not field-frozen


class Action(Event):
    """An action proposed by the agent (e.g. a tool invocation)."""

    action_type: str


class Observation(Event):
    """The result of executing an action."""

    observation_type: str
    content: str
    success: bool = True


class Message(Event):
    """A chat message from user, assistant, or system."""

    role: str  # 'user' | 'assistant' | 'system'
    content: str


class ToolCallAction(Action):
    action_type: str = "tool_call"
    tool_name: str
    tool_args: Dict[str, Any]


class ToolResultObservation(Observation):
    observation_type: str = "tool_result"
    tool_name: str
    tool_call_id: str


class FileReadAction(Action):
    action_type: str = "file_read"
    path: str


class FileReadObservation(Observation):
    observation_type: str = "file_read"
    path: str


class ShellCommandAction(Action):
    action_type: str = "shell_command"
    command: str
    cwd: Optional[str] = None


class ShellCommandObservation(Observation):
    observation_type: str = "shell_command"
    command: str
    exit_code: int


class ConfirmationRequiredEvent(Event):
    """Emitted when a tool call requires user confirmation before it can execute."""

    source: str = "system"
    tool_name: str
    tool_args: Dict[str, Any]
    risk: str
    tool_call_raw: Dict[str, Any]  # original tool_call dict; stored for resume
