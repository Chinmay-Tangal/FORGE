"""
forge/mcp/protocol.py — Model Context Protocol (MCP) JSON-RPC 2.0 definitions.

Implements the official Model Context Protocol (MCP) specification:
- JSON-RPC 2.0 messages (Request, Response, Notification, Error)
- Lifecycle: initialize, ping
- Tool discovery: tools/list
- Tool execution: tools/call
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# JSON-RPC 2.0 Base Models
class JSONRPCMessage(BaseModel):
    jsonrpc: str = "2.0"


class JSONRPCRequest(JSONRPCMessage):
    id: int | str
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCNotification(JSONRPCMessage):
    method: str
    params: Optional[Dict[str, Any]] = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCResponse(JSONRPCMessage):
    id: Optional[int | str] = None
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None


# MCP Specific Models
class MCPToolDefinition(BaseModel):
    """An MCP Tool exposed by an MCP Server."""
    name: str
    description: str = ""
    inputSchema: Dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})

    def to_openai_schema(self, server_prefix: str = "") -> Dict[str, Any]:
        """Convert MCP tool definition to OpenAI function-calling format."""
        tool_name = f"{server_prefix}__{self.name}" if server_prefix else self.name
        return {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": self.description or f"MCP tool: {self.name}",
                "parameters": self.inputSchema or {"type": "object", "properties": {}},
            },
        }


class MCPContentItem(BaseModel):
    """Result content item from a tool call."""
    type: str = "text"
    text: Optional[str] = None
    data: Optional[str] = None
    mimeType: Optional[str] = None


class MCPCallToolResult(BaseModel):
    """Result of calling an MCP tool."""
    content: List[MCPContentItem] = Field(default_factory=list)
    isError: bool = False

    def to_string(self) -> str:
        """Flatten content items into a single string output."""
        texts = [item.text for item in self.content if item.text is not None]
        if texts:
            return "\n".join(texts)
        if self.content:
            return str([item.model_dump() for item in self.content])
        return ""
