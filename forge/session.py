"""
forge/session.py — Session persistence (crash-safe JSONL event log).

Each session is stored as a JSONL file:
    .forge/sessions/<session-id>.jsonl

Line format::

    {"_type": "_meta", "session_id": "...", "status": "active", ...}  ← header
    {"_type": "Message", "role": "user", "content": "...", ...}        ← events
    ...

The ``_type`` discriminator drives reconstruction via ``_EVENT_REGISTRY``.
New event types added to ``forge.core.events`` must be registered below.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from forge.core.events import (
    Action,
    Event,
    FileReadAction,
    FileReadObservation,
    Message,
    Observation,
    ShellCommandAction,
    ShellCommandObservation,
    ToolCallAction,
    ToolResultObservation,
)
from forge.core.state import ConversationState

logger = logging.getLogger(__name__)

# Event type registry — update this when new Event subclasses are added
_EVENT_REGISTRY: Dict[str, Type[Event]] = {
    "Event": Event,
    "Action": Action,
    "Observation": Observation,
    "Message": Message,
    "ToolCallAction": ToolCallAction,
    "ToolResultObservation": ToolResultObservation,
    "FileReadAction": FileReadAction,
    "FileReadObservation": FileReadObservation,
    "ShellCommandAction": ShellCommandAction,
    "ShellCommandObservation": ShellCommandObservation,
}

# Helpers
def generate_session_id() -> str:
    """Generate a human-readable session ID: YYYYMMDD-HHMMSS-<8hex>."""
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def _event_to_dict(event: Event) -> Dict[str, Any]:
    data = json.loads(event.model_dump_json())
    data["_type"] = type(event).__name__
    return data


def _dict_to_event(data: Dict[str, Any]) -> Optional[Event]:
    type_name = data.pop("_type", None)
    cls = _EVENT_REGISTRY.get(type_name, Event)
    try:
        return cls(**data)
    except Exception as exc:
        logger.warning("Could not reconstruct event type %r: %s", type_name, exc)
        return None

# SessionManager
class SessionManager:
    """
    Saves and loads ConversationState as JSONL session files.

    Parameters
    ----------
    sessions_dir:
        Directory where ``.jsonl`` session files are stored.
        Created automatically if it doesn't exist.
    """

    def __init__(self, sessions_dir: str = ".forge/sessions") -> None:
        self.sessions_dir = os.path.abspath(sessions_dir)
        os.makedirs(self.sessions_dir, exist_ok=True)

    def _path(self, session_id: str) -> str:
        return os.path.join(self.sessions_dir, f"{session_id}.jsonl")

    def save(self, state: ConversationState, session_id: str) -> str:
        """
        Atomically persist a ConversationState.

        Writes to a ``.tmp`` file first, then ``os.replace``-renames to avoid
        leaving a corrupt file if the process is interrupted mid-write.

        Returns the path written.
        """
        path = self._path(session_id)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                meta = {
                    "_type": "_meta",
                    "session_id": session_id,
                    "status": state.status,
                    "cost": state.cost,
                    "confirmation_policy": state.confirmation_policy,
                    "working_context": state.working_context,
                    "saved_at": datetime.utcnow().isoformat(),
                }
                fh.write(json.dumps(meta) + "\n")
                for event in state.events:
                    fh.write(json.dumps(_event_to_dict(event)) + "\n")
            os.replace(tmp, path)
        except Exception as exc:
            logger.error("Failed to save session %s: %s", session_id, exc)
            if os.path.exists(tmp):
                os.remove(tmp)
        return path

    def load(self, session_id: str) -> ConversationState:
        """
        Load a ConversationState from a JSONL session file.

        Raises FileNotFoundError if the session does not exist.
        """
        path = self._path(session_id)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Session '{session_id}' not found at {path}")

        state = ConversationState()
        with open(path, "r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.warning("Skipping malformed line %d in %s: %s", i + 1, path, exc)
                    continue
                if data.get("_type") == "_meta":
                    state.status = data.get("status", "active")
                    state.cost = float(data.get("cost", 0.0))
                    state.confirmation_policy = data.get("confirmation_policy", "auto")
                    state.working_context = data.get("working_context", "")
                else:
                    event = _dict_to_event(data)
                    if event:
                        state.events.append(event)
        logger.info("Loaded session '%s' (%d events).", session_id, len(state.events))
        return state

    def list(self) -> List[Dict[str, Any]]:
        """Return metadata for all sessions, sorted newest-first."""
        sessions: List[Dict[str, Any]] = []
        if not os.path.isdir(self.sessions_dir):
            return sessions
        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".jsonl"):
                continue
            session_id = fname[:-6]
            path = os.path.join(self.sessions_dir, fname)
            saved_at, status, event_count = "", "unknown", 0
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get("_type") == "_meta":
                            saved_at = data.get("saved_at", "")
                            status = data.get("status", "unknown")
                        elif not data.get("_type", "").startswith("_"):
                            event_count += 1
            except Exception as exc:
                logger.warning("Could not read session %s: %s", session_id, exc)
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
        """Delete a session file. Returns True if a file was removed."""
        path = self._path(session_id)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False
