"""tests/test_config.py — Unit tests for forge.config."""
from __future__ import annotations

import os

import pytest

from forge.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.workspace_type == "local"
    assert cfg.security_policy == "auto"
    assert cfg.max_iterations == 30
    assert cfg.context_limit == 6000


def test_load_missing_file():
    cfg = Config.load("/nonexistent/path/config.toml")
    assert cfg.local_model == "qwen2.5-coder-7b"  # default


def test_load_from_toml(tmp_dir):
    toml_path = os.path.join(tmp_dir, "config.toml")
    with open(toml_path, "w") as fh:
        fh.write('local_model = "my-model"\nsecurity_policy = "strict"\n')
    cfg = Config.load(toml_path)
    assert cfg.local_model == "my-model"
    assert cfg.security_policy == "strict"


def test_unknown_key_ignored(tmp_dir, caplog):
    toml_path = os.path.join(tmp_dir, "config.toml")
    with open(toml_path, "w") as fh:
        fh.write('nonexistent_key = "value"\n')
    cfg = Config.load(toml_path)
    assert not hasattr(cfg, "nonexistent_key")


def test_save_and_reload(tmp_dir):
    cfg = Config(local_model="test-model", max_iterations=5)
    path = os.path.join(tmp_dir, "config.toml")
    cfg.save(path)
    loaded = Config.load(path)
    assert loaded.local_model == "test-model"
    assert loaded.max_iterations == 5


def test_env_var_override(monkeypatch):
    monkeypatch.setenv("FORGE_FRONTIER_KEY", "sk-test-123")
    cfg = Config.load("/nonexistent.toml")
    assert cfg.frontier_api_key == "sk-test-123"
