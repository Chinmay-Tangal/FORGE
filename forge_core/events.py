from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

class Event(BaseModel):
    """Base class for all events in the event-sourced system."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = "agent"  # 'agent', 'user', 'system'

class Action(Event):
    """An action proposed by the agent (e.g., tool call)."""
    action_type: str

class Observation(Event):
    """The result of an action (e.g., tool execution output)."""
    observation_type: str
    content: str
    success: bool = True

class Message(Event):
    """A chat message (from user, agent, or system)."""
    role: str # 'user', 'assistant', 'system'
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
