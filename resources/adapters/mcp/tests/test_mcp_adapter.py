"""Unit tests for the Core L0 MCP adapter."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resources.adapters.mcp.adapter import (
    McpAdapterHealthStatus,
    McpServerHealthStatus,
    McpToolInfo,
    McpToolResult,
)
from resources.adapters.mcp.config import McpAdapterSettings


class TestMcpToolInfo:
    """McpToolInfo validation."""

    def test_valid(self) -> None:
        info = McpToolInfo(
            server_id="fs",
            tool_name="read_file",
            description="Read a file from disk",
            input_schema={"type": "object"},
        )
        assert info.server_id == "fs"
        assert info.tool_name == "read_file"

    def test_rejects_empty_server_id(self) -> None:
        with pytest.raises(ValidationError):
            McpToolInfo(server_id="", tool_name="t")

    def test_rejects_empty_tool_name(self) -> None:
        with pytest.raises(ValidationError):
            McpToolInfo(server_id="s", tool_name="")

    def test_null_schema(self) -> None:
        info = McpToolInfo(server_id="s", tool_name="t")
        assert info.input_schema is None
        assert info.description == ""


class TestMcpToolResult:
    """McpToolResult validation."""

    def test_valid(self) -> None:
        result = McpToolResult(
            content=[{"type": "text", "text": "hello"}],
            is_error=False,
        )
        assert len(result.content) == 1
        assert result.is_error is False

    def test_error_result(self) -> None:
        result = McpToolResult(content=[], is_error=True)
        assert result.is_error is True


class TestMcpAdapterHealthStatus:
    """McpAdapterHealthStatus validation."""

    def test_healthy(self) -> None:
        status = McpAdapterHealthStatus(
            ready=True,
            servers=(
                McpServerHealthStatus(
                    server_id="fs",
                    connected=True,
                    tool_count=3,
                    detail="ok",
                ),
            ),
            detail="ok",
        )
        assert status.ready is True
        assert len(status.servers) == 1

    def test_unhealthy(self) -> None:
        status = McpAdapterHealthStatus(ready=False, servers=(), detail="unreachable")
        assert status.ready is False


class TestMcpAdapterSettings:
    """McpAdapterSettings validation."""

    def test_defaults(self) -> None:
        settings = McpAdapterSettings()
        assert settings.base_url == "http://brain-mcp:8763"
        assert settings.timeout_seconds == 10.0

    def test_custom_url(self) -> None:
        settings = McpAdapterSettings(base_url="http://localhost:9999")
        assert settings.base_url == "http://localhost:9999"

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(ValidationError):
            McpAdapterSettings(base_url="")

    def test_rejects_negative_timeout(self) -> None:
        with pytest.raises(ValidationError):
            McpAdapterSettings(timeout_seconds=-1)
