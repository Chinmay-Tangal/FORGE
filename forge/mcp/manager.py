"""
forge/mcp/manager.py — MCP Server Manager and ToolRegistry integration.

Loads MCP server definitions from ``.forge/mcp.json`` or configuration,
manages active client processes, and bridges MCP tools into Forge's ToolRegistry.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from forge.mcp.client import MCPClient
from forge.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPManager:
    """
    Manages active MCP client connections and registers their tools with ToolRegistry.

    Configuration file format (``.forge/mcp.json``)::

        {
            "mcpServers": {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
                },
                "postgres": {
                    "command": "uvx",
                    "args": ["mcp-server-postgres", "--connection-string", "..."]
                }
            }
        }
    """

    def __init__(self, config_path: str = ".forge/mcp.json") -> None:
        self.config_path = os.path.abspath(config_path)
        self.clients: Dict[str, MCPClient] = {}

    def load_and_connect(self, registry: Optional[ToolRegistry] = None) -> int:
        """
        Load MCP configuration and connect to all defined servers.
        Returns the number of successfully registered MCP tools.
        """
        if not os.path.isfile(self.config_path):
            logger.debug("No MCP config found at %s.", self.config_path)
            return 0

        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Failed to parse MCP config %s: %s", self.config_path, exc)
            return 0

        servers = data.get("mcpServers", {})
        registered_count = 0

        for name, srv in servers.items():
            cmd = srv.get("command")
            if not cmd:
                continue
            args = srv.get("args", [])
            env = srv.get("env", {})
            cwd = srv.get("cwd")

            client = MCPClient(name=name, command=cmd, args=args, env=env, cwd=cwd)
            if client.connect():
                self.clients[name] = client
                if registry is not None:
                    count = self._register_tools(client, registry)
                    registered_count += count

        return registered_count

    def _register_tools(self, client: MCPClient, registry: ToolRegistry) -> int:
        """Register all tools from an MCP client into the tool registry."""
        count = 0
        for tool_def in client.tools:
            registered_name = f"mcp__{client.name}__{tool_def.name}"

            # Factory function to capture client and tool name in closure
            def make_tool_func(c: MCPClient, t_name: str):
                def mcp_tool_wrapper(**kwargs) -> str:
                    result = c.call_tool(t_name, kwargs)
                    return result.to_string()
                return mcp_tool_wrapper

            fn = make_tool_func(client, tool_def.name)

            registry.register(
                name=registered_name,
                description=f"[{client.name.upper()} MCP] {tool_def.description}",
                parameters=tool_def.inputSchema,
            )(fn)
            count += 1
            logger.info("Registered MCP tool: %s", registered_name)

        return count

    def get_status(self) -> List[Dict[str, Any]]:
        """Return a summary of all MCP server connections and tools."""
        statuses = []
        for name, client in self.clients.items():
            is_alive = client.ping() if client._connected else False
            statuses.append({
                "name": name,
                "command": client.command,
                "connected": is_alive,
                "tools": [t.name for t in client.tools],
            })
        return statuses

    def shutdown(self) -> None:
        """Close all active MCP client processes."""
        for client in self.clients.values():
            try:
                client.close()
            except Exception:
                pass
        self.clients.clear()
