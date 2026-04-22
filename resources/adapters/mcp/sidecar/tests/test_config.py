"""Unit tests for MCP Adapter sidecar configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from config import McpAdapterConfig, McpServerConfig


class TestMcpServerConfig:
    """McpServerConfig validation."""

    def test_stdio_server_config(self) -> None:
        cfg = McpServerConfig(
            transport="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]

    def test_http_server_config(self) -> None:
        cfg = McpServerConfig(
            transport="http",
            url="http://localhost:7411/eventkit/rpc",
            headers={"Authorization": "Bearer token"},
        )
        assert cfg.transport == "http"
        assert cfg.url == "http://localhost:7411/eventkit/rpc"
        assert cfg.headers["Authorization"] == "Bearer token"

    def test_rejects_invalid_transport(self) -> None:
        with pytest.raises(ValidationError):
            McpServerConfig(transport="websocket")

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            McpServerConfig(transport="stdio", command="echo", bogus="field")


class TestMcpAdapterConfig:
    """McpAdapterConfig validation."""

    def test_defaults(self) -> None:
        cfg = McpAdapterConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8763
        assert cfg.timeout_seconds == 30.0
        assert cfg.servers == {}

    def test_full_config(self) -> None:
        cfg = McpAdapterConfig(
            host="127.0.0.1",
            port=9000,
            timeout_seconds=15.0,
            servers={
                "fs": McpServerConfig(transport="stdio", command="echo"),
            },
        )
        assert cfg.port == 9000
        assert "fs" in cfg.servers

    def test_rejects_invalid_port(self) -> None:
        with pytest.raises(ValidationError):
            McpAdapterConfig(port=0)

    def test_rejects_negative_timeout(self) -> None:
        with pytest.raises(ValidationError):
            McpAdapterConfig(timeout_seconds=-1)
