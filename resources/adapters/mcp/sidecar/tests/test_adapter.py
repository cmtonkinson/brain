"""Unit tests for MCP client manager."""

from __future__ import annotations

import pytest

from adapter import (
    McpClientManager,
    McpServerConnectionError,
    ServerStatus,
    ToolCallResult,
    ToolInfo,
)
from config import McpAdapterConfig, McpServerConfig


class TestToolInfo:
    """ToolInfo serialization."""

    def test_to_dict(self) -> None:
        info = ToolInfo(
            server_id="fs",
            tool_name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
        d = info.to_dict()
        assert d["server_id"] == "fs"
        assert d["tool_name"] == "read_file"
        assert d["description"] == "Read a file"
        assert d["input_schema"]["type"] == "object"

    def test_to_dict_null_schema(self) -> None:
        info = ToolInfo(
            server_id="s",
            tool_name="t",
            description="",
            input_schema=None,
        )
        assert info.to_dict()["input_schema"] is None


class TestToolCallResult:
    """ToolCallResult serialization."""

    def test_to_dict(self) -> None:
        result = ToolCallResult(
            content=[{"type": "text", "text": "hello"}],
            is_error=False,
        )
        d = result.to_dict()
        assert d["content"] == [{"type": "text", "text": "hello"}]
        assert d["is_error"] is False


class TestServerStatus:
    """ServerStatus serialization."""

    def test_to_dict(self) -> None:
        s = ServerStatus(
            server_id="fs",
            connected=True,
            tool_count=3,
            detail="ok",
            instruction_summary="read files",
        )
        d = s.to_dict()
        assert d == {
            "server_id": "fs",
            "connected": True,
            "tool_count": 3,
            "detail": "ok",
            "instruction_summary": "read files",
        }


class TestMcpClientManager:
    """McpClientManager lifecycle and state."""

    def test_ready_when_no_servers_configured(self) -> None:
        manager = McpClientManager(McpAdapterConfig())
        assert manager.ready is True

    def test_not_ready_when_servers_configured_but_not_connected(self) -> None:
        config = McpAdapterConfig(
            servers={"fs": McpServerConfig(transport="stdio", command="echo")}
        )
        manager = McpClientManager(config)
        assert manager.ready is False

    def test_server_statuses_before_startup(self) -> None:
        config = McpAdapterConfig(
            servers={"fs": McpServerConfig(transport="stdio", command="echo")}
        )
        manager = McpClientManager(config)
        statuses = manager.server_statuses()
        assert len(statuses) == 1
        assert statuses[0].connected is False

    @pytest.mark.asyncio
    async def test_list_tools_empty_when_no_servers(self) -> None:
        manager = McpClientManager(McpAdapterConfig())
        async with manager.run():
            tools = await manager.list_tools()
            assert tools == []

    @pytest.mark.asyncio
    async def test_call_tool_raises_when_not_connected(self) -> None:
        manager = McpClientManager(McpAdapterConfig())
        async with manager.run():
            with pytest.raises(McpServerConnectionError):
                await manager.call_tool(
                    server_id="nonexistent",
                    tool_name="some_tool",
                    arguments={},
                )
