from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from forge_core.events import Event, Message, Action, Observation

class ConversationState(BaseModel):
    """Mutable object holding the event log and metadata. Immutable events."""
    events: List[Event] = Field(default_factory=list)
    status: str = "active" # active, paused, finished, error
    cost: float = 0.0
    confirmation_policy: str = "auto" # auto, strict
    working_context: str = "" # MemGPT style mutable working context
    
    def append_event(self, event: Event):
        self.events.append(event)
        
    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        return [e for e in self.events if isinstance(e, Message)][-limit:]
        
    def get_all_events(self) -> List[Event]:
        return self.events
        
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
