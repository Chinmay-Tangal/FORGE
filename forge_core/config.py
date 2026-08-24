"""
forge_core/config.py — Configuration loader for Forge.

Reads from `.forge/config.toml` and falls back to safe defaults.
Supports stdlib `tomllib` (Python 3.11+) with a manual fallback parser.
"""
import os
import logging
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


def _parse_toml_simple(text: str) -> dict:
    """Minimal TOML parser supporting flat key=value pairs (no tables/arrays)."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip inline comments
        if "#" in value:
            value = value[:value.index("#")].strip()
        # Bool
        if value.lower() == "true":
            result[key] = True
        elif value.lower() == "false":
            result[key] = False
        # Integer
        elif value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
            result[key] = int(value)
        # Quoted string
        elif (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            result[key] = value[1:-1]
        else:
            result[key] = value
    return result


def _load_toml(path: str) -> dict:
    """Load a TOML file using stdlib tomllib or the fallback parser."""
    try:
        import tomllib  # Python 3.11+
        with open(path, "rb") as f:
            return tomllib.load(f)
    except ImportError:
        pass
    try:
        import tomli  # optional third-party
        with open(path, "rb") as f:
            return tomli.load(f)
    except ImportError:
        pass
    # Manual fallback
    with open(path, "r", encoding="utf-8") as f:
        return _parse_toml_simple(f.read())


@dataclass
class Config:
    """Forge runtime configuration. All fields have safe defaults."""

    # Workspace
    workspace_type: str = "local"           # 'local' | 'docker'

    # Local LLM (llama-server / OpenAI-compatible)
    local_llm_url: str = "http://localhost:8080/v1"
    local_model: str = "qwen2.5-coder-7b"

    # Optional frontier LLM (e.g. OpenAI, Anthropic-compatible)
    frontier_llm_url: Optional[str] = None
    frontier_model: Optional[str] = None
    frontier_api_key: Optional[str] = None

    # Security
    security_policy: str = "auto"           # 'auto' | 'strict'

    # Agent loop
    max_iterations: int = 30
    context_limit: int = 6000               # rough token budget for in-context messages

    # Paths
    hooks_dir: str = ".forge/hooks"
    skills_dir: str = ".forge/skills"
    memory_db: str = ".forge/memory.db"
    sessions_dir: str = ".forge/sessions"

    @classmethod
    def load(cls, path: str = ".forge/config.toml") -> "Config":
        """Load config from TOML file, falling back to defaults for missing keys."""
        cfg = cls()
        if not os.path.isfile(path):
            logger.debug(f"Config file not found at {path}; using defaults.")
            return cfg
        try:
            data = _load_toml(path)
            for key, value in data.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
                else:
                    logger.warning(f"Unknown config key '{key}' in {path}; ignoring.")
        except Exception as e:
            logger.warning(f"Failed to parse config {path}: {e}. Using defaults.")
        # Allow env var override for frontier API key
        if cfg.frontier_api_key is None:
            cfg.frontier_api_key = os.environ.get("FORGE_FRONTIER_KEY")
        return cfg

    def save(self, path: str = ".forge/config.toml") -> None:
        """Persist current config to a TOML file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lines = ["# Forge configuration\n"]
        for key, value in asdict(self).items():
            if value is None:
                lines.append(f"# {key} = \"\"\n")
            elif isinstance(value, bool):
                lines.append(f"{key} = {'true' if value else 'false'}\n")
            elif isinstance(value, str):
                lines.append(f'{key} = "{value}"\n')
            else:
                lines.append(f"{key} = {value}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        logger.info(f"Config saved to {path}")
