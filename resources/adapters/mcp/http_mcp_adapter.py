"""Concrete MCP adapter implementation — thin HTTP client to the sidecar."""

from __future__ import annotations

from typing import Any

import httpx

from resources.adapters.mcp.adapter import (
    McpAdapterHealthStatus,
    McpServerConnectionError,
    McpServerHealthStatus,
    McpToolCallError,
    McpToolInfo,
    McpToolResult,
)
from resources.adapters.mcp.config import McpAdapterSettings


class HttpMcpAdapter:
    """MCP adapter that delegates to the brain-mcp sidecar over HTTP."""

    def __init__(self, *, settings: McpAdapterSettings) -> None:
        self._base_url = settings.base_url.rstrip("/")
        self._timeout = settings.timeout_seconds
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    def health(self) -> McpAdapterHealthStatus:
        """Probe sidecar health endpoint."""
        try:
            response = self._client.get("/health")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return McpAdapterHealthStatus(
                ready=False,
                servers=(),
                detail=f"sidecar unreachable: {exc}",
            )
        body = response.json()
        servers = tuple(
            McpServerHealthStatus.model_validate(s) for s in body.get("servers", [])
        )
        return McpAdapterHealthStatus(
            ready=body.get("status") == "ok",
            servers=servers,
            detail=body.get("status", "unknown"),
        )

    def list_tools(self) -> tuple[McpToolInfo, ...]:
        """Fetch all discovered tools from the sidecar."""
        try:
            response = self._client.get("/tools")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise McpServerConnectionError(f"sidecar unreachable: {exc}") from exc
        body = response.json()
        return tuple(McpToolInfo.model_validate(t) for t in body.get("tools", []))

    def list_servers(self) -> tuple[McpServerHealthStatus, ...]:
        """Fetch configured MCP server statuses and operator-facing summaries."""
        try:
            response = self._client.get("/servers")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise McpServerConnectionError(f"sidecar unreachable: {exc}") from exc
        body = response.json()
        return tuple(
            McpServerHealthStatus.model_validate(s) for s in body.get("servers", [])
        )

    def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpToolResult:
        """Invoke one MCP tool via the sidecar."""
        try:
            response = self._client.post(
                "/tools/call",
                json={
                    "server_id": server_id,
                    "tool_name": tool_name,
                    "arguments": arguments,
                },
            )
        except httpx.HTTPError as exc:
            raise McpServerConnectionError(f"sidecar unreachable: {exc}") from exc
        if response.status_code >= 500:
            raise McpToolCallError(
                f"sidecar error {response.status_code}: {response.text}"
            )
        if response.status_code >= 400:
            raise McpToolCallError(
                f"tool call rejected {response.status_code}: {response.text}"
            )
        return McpToolResult.model_validate(response.json())
