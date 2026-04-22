"""Pydantic settings for the MCP adapter resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.mcp.component import RESOURCE_COMPONENT_ID


class McpAdapterSettings(BaseModel):
    """Core-side MCP adapter settings under ``adapter.mcp``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = Field(
        default="http://brain-mcp:8763",
        min_length=1,
    )
    timeout_seconds: float = Field(default=10.0, gt=0)


def resolve_mcp_adapter_settings(
    settings: CoreRuntimeSettings,
) -> McpAdapterSettings:
    """Resolve adapter settings from ``adapter.mcp``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=McpAdapterSettings,
    )
