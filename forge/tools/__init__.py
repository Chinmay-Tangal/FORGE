"""
forge.tools — Built-in tool registry.

Imports all tool modules so their @register decorators fire,
then exposes the populated registry for the agent to consume.
"""
from forge.tools.registry import ToolRegistry

# A single shared registry instance populated by the tool modules below.
registry = ToolRegistry()

# Side-effect imports: each module calls registry.register() on import.
import forge.tools.filesystem   # noqa: F401, E402
import forge.tools.git          # noqa: F401, E402
import forge.tools.shell        # noqa: F401, E402
import forge.memory.tools       # noqa: F401, E402  — memory tools live beside the store they wrap
import forge.codebase.tools     # noqa: F401, E402  — AST symbol intelligence tools
import forge.agent.subagent     # noqa: F401, E402  — multi-agent delegation tools

__all__ = ["registry", "ToolRegistry"]
