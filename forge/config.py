"""
forge/config.py — Runtime configuration.

Loads from ``.forge/config.toml`` using stdlib ``tomllib`` (Python 3.11+)
or a lightweight fallback parser. CLI flags always override config-file values.

Example config file::

    local_llm_url   = "http://localhost:8080/v1"
    local_model     = "qwen2.5-coder-7b"
    security_policy = "auto"
    context_limit   = 6000

Run ``forge --dump-config`` to see the full list of available settings.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# TOML parser (stdlib first, then manual fallback)

def _load_toml(path: str) -> dict:
    try:
        import tomllib
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except ImportError:
        pass
    try:
        import tomli  # optional third-party
        with open(path, "rb") as fh:
            return tomli.load(fh)
    except ImportError:
        pass
    # Manual fallback — handles flat key = value TOML
    result: dict = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("["):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if "#" in value:
                value = value[: value.index("#")].strip()
            if value.lower() == "true":
                result[key] = True
            elif value.lower() == "false":
                result[key] = False
            elif value.lstrip("-").isdigit():
                result[key] = int(value)
            elif (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                result[key] = value[1:-1]
            else:
                result[key] = value
    return result

# Config dataclass
@dataclass
class Config:
    """
    Forge runtime configuration. Every field has a safe default.

    Fields
    ------
    workspace_type : str
        ``'local'`` (default) or ``'docker'``.
    local_llm_url : str
        Base URL of the local llama-server / vLLM instance.
    local_model : str
        Model identifier sent in API requests.
    frontier_llm_url : Optional[str]
        Base URL of an optional hosted frontier LLM.
    frontier_model : Optional[str]
        Model identifier for the frontier LLM.
    frontier_api_key : Optional[str]
        Bearer token for the frontier LLM. Can also be set via
        the ``FORGE_FRONTIER_KEY`` environment variable.
    security_policy : str
        ``'auto'`` (confirm only HIGH-risk) or ``'strict'`` (confirm MEDIUM+HIGH).
    max_iterations : int
        Maximum tool-call iterations per user turn before the agent gives up.
    context_limit : int
        Rough token budget for in-context events before the condenser fires.
    hooks_dir : str
        Directory containing pre_<tool>.sh / post_<tool>.sh hook scripts.
    skills_dir : str
        Directory containing Markdown skill files.
    memory_db : str
        Path to the SQLite memory database.
    sessions_dir : str
        Directory where JSONL session files are persisted.
    """

    workspace_type: str = "local"
    local_llm_url: str = "http://localhost:8080/v1"
    local_model: str = "qwen2.5-coder-7b"
    frontier_llm_url: Optional[str] = None
    frontier_model: Optional[str] = None
    frontier_api_key: Optional[str] = None
    security_policy: str = "auto"
    max_iterations: int = 30
    context_limit: int = 6000
    hooks_dir: str = ".forge/hooks"
    skills_dir: str = ".forge/skills"
    memory_db: str = ".forge/memory.db"
    sessions_dir: str = ".forge/sessions"

    @classmethod
    def load(cls, path: str = ".forge/config.toml") -> "Config":
        """Load config from a TOML file, falling back to defaults for missing keys."""
        cfg = cls()
        if not os.path.isfile(path):
            logger.debug("No config file at %s — using defaults.", path)
        else:
            try:
                data = _load_toml(path)
                for key, value in data.items():
                    if hasattr(cfg, key):
                        setattr(cfg, key, value)
                    else:
                        logger.warning("Unknown config key %r in %s — ignoring.", key, path)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s — using defaults.", path, exc)
        # Environment variable override (always applied, regardless of file presence)
        if cfg.frontier_api_key is None:
            cfg.frontier_api_key = os.environ.get("FORGE_FRONTIER_KEY")
        return cfg

    def save(self, path: str = ".forge/config.toml") -> None:
        """Write current config to a TOML file."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        lines = ["# Forge configuration — generated by `forge --dump-config`\n\n"]
        for key, value in asdict(self).items():
            if value is None:
                lines.append(f"# {key} = \"\"\n")
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}\n")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"\n')
            else:
                lines.append(f"{key} = {value}\n")
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        logger.info("Config saved to %s.", path)
