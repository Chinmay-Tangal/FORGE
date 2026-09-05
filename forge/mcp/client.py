"""
forge/mcp/client.py — Stdio-based Model Context Protocol (MCP) Client.

Manages the lifecycle of an MCP server process communicating over stdio using
JSON-RPC 2.0 messages formatted as newline-delimited JSON.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any, Dict, List, Optional

from forge.mcp.protocol import (
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPCallToolResult,
    MCPToolDefinition,
)

logger = logging.getLogger(__name__)


class MCPClient:
    """
    Client for an individual MCP Server running as a subprocess over stdio.

    Parameters
    ----------
    name : str
        Human-readable identifier for the server (e.g. 'github', 'filesystem').
    command : str
        Command to execute (e.g. 'npx', 'python', 'uvx').
    args : List[str]
        Arguments passed to the command.
    env : Optional[Dict[str, str]]
        Extra environment variables for the subprocess.
    cwd : Optional[str]
        Working directory for the subprocess.
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._connected = False
        self.tools: List[MCPToolDefinition] = []

    def connect(self, timeout: float = 10.0) -> bool:
        """Start the MCP server process and complete the initialize handshake."""
        full_env = os.environ.copy()
        full_env.update(self.env)

        cmd_list = [self.command] + self.args
        try:
            self.process = subprocess.Popen(
                cmd_list,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self.cwd,
                env=full_env,
            )
        except Exception as exc:
            logger.error("Failed to start MCP server '%s' (%s): %s", self.name, self.command, exc)
            return False

        # 1. Send 'initialize' request
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
            },
            "clientInfo": {
                "name": "Forge",
                "version": "0.2.0",
            },
        }

        try:
            resp = self._send_request("initialize", init_params, timeout=timeout)
            if not resp or resp.error:
                err_msg = resp.error.message if resp and resp.error else "No response"
                logger.warning("MCP server '%s' initialize failed: %s", self.name, err_msg)
                self.close()
                return False

            # 2. Send 'notifications/initialized'
            self._send_notification("notifications/initialized", {})

            self._connected = True
            logger.info("Connected to MCP server '%s'.", self.name)

            # 3. Discover available tools
            self.list_tools(timeout=timeout)
            return True
        except Exception as exc:
            logger.error("Error during MCP handshake with '%s': %s", self.name, exc)
            self.close()
            return False

    def list_tools(self, timeout: float = 10.0) -> List[MCPToolDefinition]:
        """Fetch the list of tools offered by this MCP server."""
        if not self._connected or not self.process:
            return []

        resp = self._send_request("tools/list", {}, timeout=timeout)
        if not resp or resp.error or not resp.result:
            return []

        tools_data = resp.result.get("tools", [])
        self.tools = []
        for td in tools_data:
            try:
                self.tools.append(MCPToolDefinition(**td))
            except Exception as exc:
                logger.warning("Failed to parse MCP tool in '%s': %s", self.name, exc)

        logger.debug("Discovered %d tool(s) from MCP server '%s'.", len(self.tools), self.name)
        return self.tools

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout: float = 60.0) -> MCPCallToolResult:
        """Invoke a tool on the MCP server."""
        if not self._connected or not self.process:
            return MCPCallToolResult(isError=True, content=[{"type": "text", "text": f"MCP server '{self.name}' is not connected."}])

        params = {"name": name, "arguments": arguments}
        resp = self._send_request("tools/call", params, timeout=timeout)

        if not resp:
            return MCPCallToolResult(isError=True, content=[{"type": "text", "text": f"Timeout calling MCP tool '{name}' on '{self.name}'."}])

        if resp.error:
            return MCPCallToolResult(isError=True, content=[{"type": "text", "text": f"MCP Error ({resp.error.code}): {resp.error.message}"}])

        result_dict = resp.result or {}
        return MCPCallToolResult(**result_dict)

    def ping(self, timeout: float = 3.0) -> bool:
        """Send a ping to verify server liveness."""
        if not self._connected or not self.process or self.process.poll() is not None:
            return False
        resp = self._send_request("ping", {}, timeout=timeout)
        return resp is not None and resp.error is None

    def _send_request(self, method: str, params: Dict[str, Any], timeout: float = 10.0) -> Optional[JSONRPCResponse]:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return None

            self._request_id += 1
            req_id = self._request_id
            req = JSONRPCRequest(id=req_id, method=method, params=params)
            msg_str = req.model_dump_json() + "\n"

            try:
                self.process.stdin.write(msg_str)  # type: ignore[union-attr]
                self.process.stdin.flush()  # type: ignore[union-attr]

                # Wait for line response
                # Note: stdout reading is blocking per line
                line = self.process.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    return None
                data = json.loads(line.strip())
                return JSONRPCResponse(**data)
            except Exception as exc:
                logger.error("Error communicating with MCP server '%s': %s", self.name, exc)
                return None

    def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return
            notif = JSONRPCNotification(method=method, params=params)
            msg_str = notif.model_dump_json() + "\n"
            try:
                self.process.stdin.write(msg_str)  # type: ignore[union-attr]
                self.process.stdin.flush()  # type: ignore[union-attr]
            except Exception as exc:
                logger.error("Error sending notification to MCP server '%s': %s", self.name, exc)

    def close(self) -> None:
        """Terminate the server process."""
        self._connected = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2.0)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
        logger.debug("Closed MCP server '%s'.", self.name)
