"""
forge/tools/registry.py — Decorator-based tool registry.

Every tool is registered via ``@registry.register(...)`` and stored as a
``Tool`` object. The registry exposes tools to the LLM as OpenAI-format
function schemas and dispatches calls to the underlying Python functions.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Tool(BaseModel):
    """Metadata + callable for a registered tool."""

    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable

    model_config = {"arbitrary_types_allowed": True}


class ToolRegistry:
    """
    Central registry of all tools available to the agent.

    Usage::

        registry = ToolRegistry()

        @registry.register(
            name="my_tool",
            description="Does something useful.",
            parameters={"type": "object", "properties": {...}, "required": [...]},
        )
        def my_tool(arg: str) -> str:
            ...
    """

    def __init__(self) -> None:
        self.tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: Dict[str, Any]) -> Callable:
        """Decorator that registers a function as a named tool."""
        def decorator(func: Callable) -> Callable:
            self.tools[name] = Tool(
                name=name,
                description=description,
                parameters=parameters,
                func=func,
            )
            logger.debug("Registered tool: %s", name)
            return func
        return decorator

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name!r}")
        return self.tools[name]

    def execute(self, name: str, kwargs: Dict[str, Any]) -> Any:
        """Look up and call a tool by name."""
        return self.get(name).func(**kwargs)

    def to_openai_schema(self) -> List[Dict[str, Any]]:
        """Return the full tools list in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools.values()
        ]

    def __len__(self) -> int:
        return len(self.tools)

    def __contains__(self, name: str) -> bool:
        return name in self.tools
