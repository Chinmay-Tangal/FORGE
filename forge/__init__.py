"""
Forge — Terminal-native local agentic coding assistant.

Public API surface for library consumers:

    from forge import Agent, Config, SessionManager
    from forge.llm import LLMBackend, RouterLLM
    from forge.tools import registry
"""
__version__ = "0.2.0"
__all__ = ["Agent", "Config", "SessionManager"]

from forge.agent.loop import Agent
from forge.config import Config
from forge.session import SessionManager
