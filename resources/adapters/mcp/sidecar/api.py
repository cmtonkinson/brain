"""FastAPI HTTP API for the MCP Adapter sidecar."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from adapter import McpClientManager, McpToolCallError, McpServerConnectionError
from config import McpAdapterConfig


class ToolCallRequest(BaseModel):
    """Request body for POST /tools/call."""

    model_config = ConfigDict(extra="forbid")

    server_id: str
    tool_name: str
    arguments: dict[str, Any] = {}


def create_app(*, config: McpAdapterConfig) -> FastAPI:
    """Build the FastAPI application with lifespan-managed MCP client."""
    manager = McpClientManager(config)
    start_time = time.monotonic()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with manager.run():
            yield

    app = FastAPI(title="Brain MCP Adapter", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        status = "ok" if manager.ready else "degraded"
        return {
            "status": status,
            "uptime_seconds": round(time.monotonic() - start_time, 1),
            "servers": [s.to_dict() for s in manager.server_statuses()],
        }

    @app.get("/tools")
    async def list_tools() -> dict[str, Any]:
        tools = await manager.list_tools()
        return {"tools": [t.to_dict() for t in tools]}

    @app.post("/tools/call")
    async def call_tool(request: ToolCallRequest) -> dict[str, Any]:
        try:
            result = await manager.call_tool(
                server_id=request.server_id,
                tool_name=request.tool_name,
                arguments=request.arguments,
            )
        except McpServerConnectionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except McpToolCallError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return result.to_dict()

    return app
