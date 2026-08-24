"""tests/test_session.py — Unit tests for forge.session."""
from __future__ import annotations

import pytest

from forge.core.events import Message, ToolCallAction, ToolResultObservation
from forge.core.state import ConversationState
from forge.session import SessionManager, generate_session_id


def test_session_id_format():
    sid = generate_session_id()
    parts = sid.split("-")
    assert len(parts) == 4  # YYYYMMDD, HHMMSS, 8hex → split on 3 dashes
    assert len(parts[0]) == 8   # date


def test_save_and_load_round_trip(tmp_dir):
    sm = SessionManager(sessions_dir=tmp_dir)
    sid = generate_session_id()

    state = ConversationState()
    state.append_event(Message(role="user", content="hello"))
    state.append_event(Message(role="assistant", content="world"))
    state.working_context = "summary here"
    state.cost = 0.42

    sm.save(state, sid)
    loaded = sm.load(sid)

    assert len(loaded.events) == 2
    assert isinstance(loaded.events[0], Message)
    assert loaded.events[0].content == "hello"
    assert loaded.working_context == "summary here"
    assert loaded.cost == pytest.approx(0.42)


def test_tool_events_round_trip(tmp_dir):
    sm = SessionManager(sessions_dir=tmp_dir)
    sid = generate_session_id()

    state = ConversationState()
    state.append_event(ToolCallAction(tool_name="read_file", tool_args={"path": "foo.py"}))
    state.append_event(ToolResultObservation(
        tool_name="read_file", tool_call_id="abc", content="# code"
    ))

    sm.save(state, sid)
    loaded = sm.load(sid)

    assert len(loaded.events) == 2
    assert isinstance(loaded.events[0], ToolCallAction)
    assert loaded.events[0].tool_name == "read_file"
    assert isinstance(loaded.events[1], ToolResultObservation)


def test_load_missing_raises(tmp_dir):
    sm = SessionManager(sessions_dir=tmp_dir)
    with pytest.raises(FileNotFoundError):
        sm.load("nonexistent-session-id")


def test_list_sessions(tmp_dir):
    sm = SessionManager(sessions_dir=tmp_dir)
    assert sm.list() == []

    for i in range(3):
        state = ConversationState()
        state.append_event(Message(role="user", content=f"msg {i}"))
        sm.save(state, f"session-{i:04d}-00000000-aabbccdd"[:28])

    sessions = sm.list()
    assert len(sessions) == 3


def test_delete_session(tmp_dir):
    sm = SessionManager(sessions_dir=tmp_dir)
    sid = generate_session_id()
    state = ConversationState()
    state.append_event(Message(role="user", content="test"))
    sm.save(state, sid)

    assert sm.delete(sid) is True
    assert sm.delete(sid) is False  # already gone
