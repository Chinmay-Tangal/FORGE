"""
tests/conftest.py — Shared pytest fixtures.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from forge.config import Config
from forge.core.state import ConversationState


@pytest.fixture
def tmp_dir():
    """A temporary directory that is cleaned up after the test."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def config(tmp_dir) -> Config:
    """A Config instance pointing all paths at a temp directory."""
    return Config(
        sessions_dir=os.path.join(tmp_dir, "sessions"),
        memory_db=os.path.join(tmp_dir, "memory.db"),
        hooks_dir=os.path.join(tmp_dir, "hooks"),
        skills_dir=os.path.join(tmp_dir, "skills"),
    )


@pytest.fixture
def state() -> ConversationState:
    return ConversationState()
