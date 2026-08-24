"""
forge_core/session.py — Session save/load for crash-safe conversation resume.

Each session is stored as a JSONL file in `.forge/sessions/<session-id>.jsonl`.
One JSON line per Event, with a `_type` discriminator for reconstruction.
"""
import os
import json
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional, Any

from forge_core.state import ConversationState
from forge_core.events import (
    Event, Message, Action, Observation,
    ToolCallAction, ToolResultObservation,
    FileReadAction, FileReadObservation,
    ShellCommandAction, ShellCommandObservation,
)

logger = logging.getLogger(__name__)

# Registry maps `_type` string → Pydantic class for reconstruction
_EVENT_REGISTRY: Dict[str, type] = {
    "Message": Message,
    "ToolCallAction": ToolCallAction,
    "ToolResultObservation": ToolResultObservation,
    "FileReadAction": FileReadAction,
    "FileReadObservation": FileReadObservation,
    "ShellCommandAction": ShellCommandAction,
    "ShellCommandObservation": ShellCommandObservation,
    "Action": Action,
    "Observation": Observation,
    "Event": Event,
}


def _event_to_dict(event: Event) -> Dict[str, Any]:
    """Serialize an Event to a JSON-serializable dict with type discriminator."""
    data = json.loads(event.model_dump_json())
    data["_type"] = type(event).__name__
    return data


def _dict_to_event(data: Dict[str, Any]) -> Optional[Event]:
    """Reconstruct an Event from a dict using the `_type` discriminator."""
    type_name = data.pop("_type", None)
    cls = _EVENT_REGISTRY.get(type_name, Event)
    try:
        return cls(**data)
    except Exception as e:
        logger.warning(f"Could not reconstruct event type '{type_name}': {e}")
        return None


def generate_session_id() -> str:
    """Generate a unique session ID: YYYYMMDD-HHMMSS-<8hex>."""
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"{ts}-{short}"


class SessionManager:
    """Manages persistent Forge sessions as JSONL event logs."""

    def __init__(self, sessions_dir: str = ".forge/sessions"):
        self.sessions_dir = os.path.abspath(sessions_dir)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def _session_path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.jsonl")

    def save(self, state: ConversationState, session_id: str) -> str:
        """
        Persist the ConversationState to a JSONL file.
        Overwrites the file atomically (write to .tmp then rename).
        Returns the path written.
        """
        path = self._session_path(session_id)
        tmp_path = path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                # First line: metadata header
                meta = {
                    "_type": "_meta",
                    "session_id": session_id,
                    "status": state.status,
                    "cost": state.cost,
                    "confirmation_policy": state.confirmation_policy,
                    "working_context": state.working_context,
                    "saved_at": datetime.utcnow().isoformat(),
                }
                f.write(json.dumps(meta) + "\n")
                # Remaining lines: events
                for event in state.events:
                    f.write(json.dumps(_event_to_dict(event)) + "\n")
            os.replace(tmp_path, path)
            logger.debug(f"Session saved: {path}")
        except Exception as e:
            logger.error(f"Failed to save session {session_id}: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        return path

    def load(self, session_id: str) -> ConversationState:
        """
        Load a ConversationState from a JSONL session file.
        Raises FileNotFoundError if the session doesn't exist.
        """
        path = self._session_path(session_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Session '{session_id}' not found at {path}")

        state = ConversationState()
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed line {i+1} in {path}: {e}")
                    continue

                if data.get("_type") == "_meta":
                    state.status = data.get("status", "active")
                    state.cost = data.get("cost", 0.0)
                    state.confirmation_policy = data.get("confirmation_policy", "auto")
                    state.working_context = data.get("working_context", "")
                else:
                    event = _dict_to_event(data)
                    if event:
                        state.events.append(event)

        logger.info(f"Loaded session '{session_id}' with {len(state.events)} events.")
        return state

    def list(self) -> List[Dict[str, Any]]:
        """
        List all available sessions, sorted newest-first.
        Returns a list of dicts with session_id, saved_at, event_count.
        """
        sessions = []
        if not os.path.isdir(self.sessions_dir):
            return sessions

        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".jsonl"):
                continue
            session_id = fname[:-6]
            path = os.path.join(self.sessions_dir, fname)
            saved_at = ""
            event_count = 0
            status = "unknown"
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "_meta":
                            saved_at = data.get("saved_at", "")
                            status = data.get("status", "unknown")
                        elif not data.get("_type", "").startswith("_"):
                            event_count += 1
            except Exception as e:
                logger.warning(f"Could not read session {session_id}: {e}")

            sessions.append({
                "session_id": session_id,
                "saved_at": saved_at,
                "event_count": event_count,
                "status": status,
                "path": path,
            })

        sessions.sort(key=lambda s: s.get("saved_at", ""), reverse=True)
        return sessions

    def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted."""
        path = self._session_path(session_id)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False
