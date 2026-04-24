"""MCP client manager — connects to configured servers and manages sessions."""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack, asynccontextmanager
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from config import McpAdapterConfig, McpServerConfig

logger = logging.getLogger(__name__)


class McpClientError(Exception):
    """Base exception for MCP client operations."""


class McpServerConnectionError(McpClientError):
    """Failed to connect to an MCP server."""


class McpToolCallError(McpClientError):
    """An MCP tool call returned an error or failed."""


class ToolInfo:
    """One discovered MCP tool."""

    __slots__ = ("server_id", "tool_name", "description", "input_schema")

    def __init__(
        self,
        *,
        server_id: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any] | None,
    ) -> None:
        self.server_id = server_id
        self.tool_name = tool_name
        self.description = description
        self.input_schema = input_schema

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolCallResult:
    """Result of one MCP tool invocation."""

    __slots__ = ("content", "is_error")

    def __init__(self, *, content: list[dict[str, Any]], is_error: bool) -> None:
        self.content = content
        self.is_error = is_error

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {"content": self.content, "is_error": self.is_error}


class ServerStatus:
    """Status and operator-facing hint metadata for one MCP server."""

    __slots__ = (
        "server_id",
        "connected",
        "tool_count",
        "detail",
        "instruction_summary",
    )

    def __init__(
        self,
        *,
        server_id: str,
        connected: bool,
        tool_count: int,
        detail: str,
        instruction_summary: str,
    ) -> None:
        self.server_id = server_id
        self.connected = connected
        self.tool_count = tool_count
        self.detail = detail
        self.instruction_summary = instruction_summary

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "server_id": self.server_id,
            "connected": self.connected,
            "tool_count": self.tool_count,
            "detail": self.detail,
            "instruction_summary": self.instruction_summary,
        }


class McpClientManager:
    """Manages MCP server connections and tool enumeration.

    Must be used as an async context manager to ensure MCP sessions are
    entered and exited in the same task (required by anyio cancel scopes).
    """

    def __init__(self, config: McpAdapterConfig) -> None:
        self._config = config
        self._sessions: dict[str, ClientSession] = {}
        self._tools_cache: dict[str, list[ToolInfo]] = {}
        self._server_errors: dict[str, str] = {}

    @asynccontextmanager
    async def run(self) -> AsyncIterator[None]:
        """Async context manager that owns all MCP session lifecycles.

        Enter/exit happens in the same task, satisfying anyio cancel scope
        constraints. Meant to be used inside the FastAPI lifespan.
        """
        async with AsyncExitStack() as stack:
            await self._connect_all(stack)
            yield
        self._sessions.clear()
        self._tools_cache.clear()
        self._server_errors.clear()

    async def _connect_all(self, stack: AsyncExitStack) -> None:
        """Connect to all configured servers eagerly."""
        for server_id, server_config in self._config.servers.items():
            try:
                session = await self._connect_server(stack, server_id, server_config)
                self._sessions[server_id] = session
                tools = await self._enumerate_tools(server_id, session)
                self._tools_cache[server_id] = tools
                logger.info(
                    "mcp server connected",
                    extra={"server_id": server_id, "tool_count": len(tools)},
                )
            except BaseException as exc:  # noqa: BLE001
                # Catch BaseException to handle ExceptionGroup from anyio
                # task groups inside the MCP SDK transports.
                error_msg = f"{type(exc).__name__}: {exc}"
                self._server_errors[server_id] = error_msg
                logger.warning(
                    "mcp server connection failed",
                    extra={"server_id": server_id, "error": error_msg},
                )

    async def list_tools(self) -> list[ToolInfo]:
        """Return all discovered tools across all connected servers."""
        result: list[ToolInfo] = []
        for tools in self._tools_cache.values():
            result.extend(tools)
        return sorted(result, key=lambda t: (t.server_id, t.tool_name))

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        """Invoke one MCP tool on the specified server."""
        session = self._sessions.get(server_id)
        if session is None:
            raise McpServerConnectionError(f"server not connected: {server_id}")

        result = await session.call_tool(
            tool_name,
            arguments=arguments,
            read_timeout_seconds=timedelta(seconds=self._config.timeout_seconds),
        )
        content = [_serialize_content_item(item) for item in result.content]
        return ToolCallResult(content=content, is_error=bool(result.isError))

    def server_statuses(self) -> list[ServerStatus]:
        """Return health status for each configured server."""
        statuses: list[ServerStatus] = []
        for server_id in self._config.servers:
            connected = server_id in self._sessions
            tool_count = len(self._tools_cache.get(server_id, []))
            detail = self._server_errors.get(server_id, "ok" if connected else "not connected")
            server_config = self._config.servers[server_id]
            statuses.append(
                ServerStatus(
                    server_id=server_id,
                    connected=connected,
                    tool_count=tool_count,
                    detail=detail,
                    instruction_summary=server_config.instruction_summary,
                )
            )
        return statuses

    @property
    def ready(self) -> bool:
        """True when at least one server is connected (or none configured)."""
        if not self._config.servers:
            return True
        return len(self._sessions) > 0

    async def _connect_server(
        self,
        stack: AsyncExitStack,
        server_id: str,
        server_config: McpServerConfig,
    ) -> ClientSession:
        """Connect to one MCP server and return an initialized session."""
        if server_config.transport == "stdio":
            return await self._connect_stdio(stack, server_id, server_config)
        if server_config.transport == "http":
            return await self._connect_http(stack, server_id, server_config)
        raise ValueError(f"unsupported transport: {server_config.transport}")

    async def _connect_stdio(
        self,
        stack: AsyncExitStack,
        server_id: str,
        server_config: McpServerConfig,
    ) -> ClientSession:
        """Connect to a stdio MCP server."""
        if not server_config.command:
            raise ValueError(f"stdio server {server_id} requires a command")
        params = StdioServerParameters(
            command=server_config.command,
            args=server_config.args,
            env={**server_config.env} if server_config.env else None,
        )
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def _connect_http(
        self,
        stack: AsyncExitStack,
        server_id: str,
        server_config: McpServerConfig,
    ) -> ClientSession:
        """Connect to an HTTP (Streamable HTTP) MCP server."""
        if not server_config.url:
            raise ValueError(f"http server {server_id} requires a url")
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamablehttp_client(
                url=server_config.url,
                headers=dict(server_config.headers) if server_config.headers else None,
                timeout=timedelta(seconds=self._config.timeout_seconds),
            )
        )
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        return session

    async def _enumerate_tools(
        self,
        server_id: str,
        session: ClientSession,
    ) -> list[ToolInfo]:
        """List all tools available on one connected server."""
        result = await session.list_tools()
        tools: list[ToolInfo] = []
        for tool in result.tools:
            tools.append(
                ToolInfo(
                    server_id=server_id,
                    tool_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema if tool.inputSchema else None,
                )
            )
        return tools


def _serialize_content_item(item: object) -> dict[str, Any]:
    """Convert one MCP content item to a JSON-safe dict."""
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if isinstance(item, dict):
        return item
    return {"type": "unknown", "text": str(item)}
