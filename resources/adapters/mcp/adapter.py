"""Transport-agnostic MCP adapter contracts and DTOs."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class McpAdapterError(Exception):
    """Base exception for MCP adapter failures."""


class McpServerConnectionError(McpAdapterError):
    """MCP sidecar or upstream server is unreachable."""


class McpToolCallError(McpAdapterError):
    """An MCP tool call failed."""


class McpToolInfo(BaseModel):
    """One discovered MCP tool from a configured server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    server_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] | None = None


class McpToolResult(BaseModel):
    """Result of invoking one MCP tool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: list[dict[str, Any]]
    is_error: bool = False


class McpServerHealthStatus(BaseModel):
    """Health status for one MCP server."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    server_id: str
    connected: bool
    tool_count: int
    detail: str
    instruction_summary: str = ""


class McpAdapterHealthStatus(BaseModel):
    """MCP adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    servers: tuple[McpServerHealthStatus, ...]
    detail: str


@runtime_checkable
class McpAdapter(Protocol):
    """Protocol for interacting with the MCP sidecar service."""

    def health(self) -> McpAdapterHealthStatus:
        """Probe MCP adapter readiness."""

    def list_tools(self) -> tuple[McpToolInfo, ...]:
        """Return all discovered MCP tools across all configured servers."""

    def list_servers(self) -> tuple[McpServerHealthStatus, ...]:
        """Return configured MCP server statuses and operator-facing summaries."""

    def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpToolResult:
        """Invoke one MCP tool on the specified server."""
