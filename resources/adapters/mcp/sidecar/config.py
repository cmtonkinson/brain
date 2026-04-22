"""Configuration for the MCP Adapter sidecar service."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


_DEFAULT_CONFIG_PATH = Path("/app/config/mcp-adapter.yaml")


class McpServerConfig(BaseModel):
    """Configuration for one MCP server connection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    transport: Literal["stdio", "http"]
    instruction_summary: str = ""

    # stdio fields
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    # http fields
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)


class McpAdapterConfig(BaseModel):
    """Top-level MCP Adapter sidecar configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8763, gt=0, lt=65536)
    timeout_seconds: float = Field(default=30.0, gt=0)
    servers: dict[str, McpServerConfig] = Field(default_factory=dict)


def load_config() -> McpAdapterConfig:
    """Load adapter config from YAML file.

    Path resolved from ``MCP_ADAPTER_CONFIG_FILE`` env var, falling back
    to ``/app/config/mcp-adapter.yaml``.
    """
    config_path = Path(os.environ.get("MCP_ADAPTER_CONFIG_FILE", str(_DEFAULT_CONFIG_PATH)))
    if not config_path.exists():
        return McpAdapterConfig()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return McpAdapterConfig()
    return McpAdapterConfig.model_validate(raw)
