"""Unit tests for MCP Adapter sidecar API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from adapter import ToolInfo
from api import create_app
from config import McpAdapterConfig


def _make_app(*, tools: list[ToolInfo] | None = None) -> TestClient:
    """Build a test client with a mocked manager."""
    config = McpAdapterConfig()
    app = create_app(config=config)
    return TestClient(app)


class TestHealthEndpoint:
    """GET /health."""

    def test_health_no_servers(self) -> None:
        client = _make_app()
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "uptime_seconds" in body
        assert body["servers"] == []


class TestToolsEndpoint:
    """GET /tools."""

    def test_tools_empty(self) -> None:
        client = _make_app()
        resp = client.get("/tools")
        assert resp.status_code == 200
        assert resp.json() == {"tools": []}


class TestServersEndpoint:
    """GET /servers."""

    def test_servers_empty(self) -> None:
        client = _make_app()
        resp = client.get("/servers")
        assert resp.status_code == 200
        assert resp.json() == {"servers": []}


class TestCallToolEndpoint:
    """POST /tools/call."""

    def test_call_tool_server_not_connected(self) -> None:
        client = _make_app()
        resp = client.post(
            "/tools/call",
            json={
                "server_id": "nonexistent",
                "tool_name": "some_tool",
                "arguments": {},
            },
        )
        assert resp.status_code == 502

    def test_call_tool_rejects_extra_fields(self) -> None:
        client = _make_app()
        resp = client.post(
            "/tools/call",
            json={
                "server_id": "s",
                "tool_name": "t",
                "arguments": {},
                "extra": "bad",
            },
        )
        assert resp.status_code == 422
