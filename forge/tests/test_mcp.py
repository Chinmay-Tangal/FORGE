"""
Tests for Model Context Protocol (MCP) client, protocol serialization, and manager.
"""
import json
import pytest
from forge.mcp.protocol import (
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    MCPCallToolResult,
    MCPContentItem,
    MCPToolDefinition,
)
from forge.mcp.manager import MCPManager
from forge.tools.registry import ToolRegistry


class TestMCPProtocol:
    def test_request_serialization(self):
        req = JSONRPCRequest(id=1, method="tools/list", params={})
        d = json.loads(req.model_dump_json())
        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["method"] == "tools/list"

    def test_response_success(self):
        resp = JSONRPCResponse(id=1, result={"tools": []})
        assert resp.result == {"tools": []}
        assert resp.error is None

    def test_response_error(self):
        err = JSONRPCError(code=-32600, message="Invalid Request")
        resp = JSONRPCResponse(id=1, error=err)
        assert resp.error.code == -32600
        assert resp.error.message == "Invalid Request"

    def test_tool_definition_to_openai(self):
        td = MCPToolDefinition(
            name="query_db",
            description="Run a database query",
            inputSchema={"type": "object", "properties": {"sql": {"type": "string"}}},
        )
        openai_schema = td.to_openai_schema(server_prefix="postgres")
        assert openai_schema["type"] == "function"
        assert openai_schema["function"]["name"] == "postgres__query_db"
        assert openai_schema["function"]["description"] == "Run a database query"
        assert "sql" in openai_schema["function"]["parameters"]["properties"]

    def test_call_tool_result_to_string(self):
        res = MCPCallToolResult(
            content=[
                MCPContentItem(type="text", text="Line 1"),
                MCPContentItem(type="text", text="Line 2"),
            ]
        )
        assert res.to_string() == "Line 1\nLine 2"
        assert not res.isError


class TestMCPManager:
    def test_manager_no_config(self, tmp_path):
        cfg_file = tmp_path / "nonexistent.json"
        mgr = MCPManager(config_path=str(cfg_file))
        assert mgr.load_and_connect() == 0
        assert len(mgr.clients) == 0

    def test_manager_invalid_json(self, tmp_path):
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text("not json content", encoding="utf-8")
        mgr = MCPManager(config_path=str(cfg_file))
        assert mgr.load_and_connect() == 0

    def test_manager_register_tools_wrapper(self):
        mgr = MCPManager()
        reg = ToolRegistry()

        class MockClient:
            name = "test_server"
            tools = [
                MCPToolDefinition(
                    name="echo",
                    description="Echo input text",
                    inputSchema={"type": "object", "properties": {"msg": {"type": "string"}}},
                )
            ]

            def call_tool(self, name, args):
                return MCPCallToolResult(content=[MCPContentItem(text=f"echoed: {args.get('msg')}")])

        count = mgr._register_tools(MockClient(), reg)
        assert count == 1
        assert "mcp__test_server__echo" in reg
        result = reg.execute("mcp__test_server__echo", {"msg": "hello world"})
        assert result == "echoed: hello world"
