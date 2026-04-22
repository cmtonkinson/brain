"""Integration tests for HttpMcpAdapter against a mock sidecar."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from resources.adapters.mcp.adapter import McpServerConnectionError, McpToolCallError
from resources.adapters.mcp.config import McpAdapterSettings
from resources.adapters.mcp.http_mcp_adapter import HttpMcpAdapter


def _mock_response(
    *,
    status_code: int = 200,
    body: dict[str, Any] | None = None,
    text: str = "",
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or json.dumps(body or {})
    resp.json.return_value = body or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestHttpMcpAdapterListTools:
    """list_tools() over HTTP."""

    def test_returns_tools(self) -> None:
        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        tools_payload = {
            "tools": [
                {
                    "server_id": "fs",
                    "tool_name": "read_file",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                },
                {
                    "server_id": "fs",
                    "tool_name": "write_file",
                    "description": "Write a file",
                    "input_schema": None,
                },
            ]
        }
        with patch.object(
            adapter._client, "get", return_value=_mock_response(body=tools_payload)
        ):
            tools = adapter.list_tools()
        assert len(tools) == 2
        assert tools[0].server_id == "fs"
        assert tools[0].tool_name == "read_file"

    def test_raises_on_connection_error(self) -> None:
        import httpx

        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        with patch.object(
            adapter._client,
            "get",
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(McpServerConnectionError):
                adapter.list_tools()


class TestHttpMcpAdapterListServers:
    """list_servers() over HTTP."""

    def test_returns_servers(self) -> None:
        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        payload = {
            "servers": [
                {
                    "server_id": "filesystem-ro",
                    "connected": True,
                    "tool_count": 4,
                    "detail": "ok",
                    "instruction_summary": "read access to home",
                }
            ]
        }
        with patch.object(
            adapter._client, "get", return_value=_mock_response(body=payload)
        ):
            servers = adapter.list_servers()

        assert len(servers) == 1
        assert servers[0].server_id == "filesystem-ro"
        assert servers[0].instruction_summary == "read access to home"


class TestHttpMcpAdapterCallTool:
    """call_tool() over HTTP."""

    def test_successful_call(self) -> None:
        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        result_payload = {
            "content": [{"type": "text", "text": "hello"}],
            "is_error": False,
        }
        with patch.object(
            adapter._client,
            "post",
            return_value=_mock_response(body=result_payload),
        ):
            result = adapter.call_tool(
                server_id="fs",
                tool_name="read_file",
                arguments={"path": "/tmp/test.txt"},
            )
        assert result.is_error is False
        assert result.content[0]["text"] == "hello"

    def test_server_error_raises(self) -> None:
        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        with patch.object(
            adapter._client,
            "post",
            return_value=_mock_response(status_code=502, text="bad gateway"),
        ):
            with pytest.raises(McpToolCallError):
                adapter.call_tool(server_id="fs", tool_name="t", arguments={})


class TestHttpMcpAdapterHealth:
    """health() over HTTP."""

    def test_healthy(self) -> None:
        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        health_payload = {
            "status": "ok",
            "uptime_seconds": 42.0,
            "servers": [
                {"server_id": "fs", "connected": True, "tool_count": 3, "detail": "ok"},
            ],
        }
        with patch.object(
            adapter._client, "get", return_value=_mock_response(body=health_payload)
        ):
            status = adapter.health()
        assert status.ready is True
        assert len(status.servers) == 1

    def test_unreachable(self) -> None:
        import httpx

        adapter = HttpMcpAdapter(
            settings=McpAdapterSettings(base_url="http://test:8763")
        )
        with patch.object(
            adapter._client,
            "get",
            side_effect=httpx.ConnectError("refused"),
        ):
            status = adapter.health()
        assert status.ready is False
        assert "unreachable" in status.detail
