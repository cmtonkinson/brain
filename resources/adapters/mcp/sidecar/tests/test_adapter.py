"""Unit tests for MCP client manager."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

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


_FIXTURE_SERVER = str(Path(__file__).with_name("fixture_server.py"))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def http_server_url() -> Iterator[str]:
    """Run the fixture server over Streamable HTTP and yield its endpoint."""
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, _FIXTURE_SERVER, "http", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                if time.monotonic() > deadline or process.poll() is not None:
                    raise RuntimeError("fixture MCP server did not start") from None
                time.sleep(0.1)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.terminate()
        process.wait(timeout=10)


class TestMcpClientManagerAgainstServer:
    """McpClientManager against a real MCP server."""

    @pytest.mark.asyncio
    async def test_stdio_server_tools_and_results(self) -> None:
        config = McpAdapterConfig(
            servers={
                "fx": McpServerConfig(
                    transport="stdio", command=sys.executable, args=[_FIXTURE_SERVER]
                )
            }
        )
        manager = McpClientManager(config)
        async with manager.run():
            assert manager.server_statuses()[0].connected is True
            tools = {tool.tool_name: tool for tool in await manager.list_tools()}
            assert tools["echo"].input_schema is not None
            assert tools["echo"].input_schema["required"] == ["text"]

            echoed = await manager.call_tool(
                server_id="fx", tool_name="echo", arguments={"text": "hi"}
            )
            assert echoed.is_error is False
            assert echoed.content[0]["text"] == "hi"

            image = await manager.call_tool(server_id="fx", tool_name="pixel", arguments={})
            assert image.content[0]["mimeType"] == "image/png"

            failed = await manager.call_tool(server_id="fx", tool_name="fail", arguments={})
            assert failed.is_error is True

    @pytest.mark.asyncio
    async def test_http_server_receives_configured_headers(self, http_server_url: str) -> None:
        config = McpAdapterConfig(
            servers={
                "fx": McpServerConfig(
                    transport="http", url=http_server_url, headers={"X-Test": "present"}
                )
            }
        )
        manager = McpClientManager(config)
        async with manager.run():
            assert manager.server_statuses()[0].connected is True
            result = await manager.call_tool(server_id="fx", tool_name="test_header", arguments={})
            assert result.is_error is False
            assert result.content[0]["text"] == "present"
