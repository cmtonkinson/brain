"""Transport-agnostic UTCP code-mode adapter contracts and DTOs."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class UtcpCodeModeAdapterError(Exception):
    """Base exception for UTCP code-mode adapter failures."""


class UtcpCodeModeConfigSchemaError(UtcpCodeModeAdapterError):
    """UTCP config does not satisfy expected schema."""


class UtcpOperatorCodeModeDefaults(BaseModel):
    """Defaults for UTCP code-mode config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_template_type: Literal["mcp"]


class UtcpOperatorCodeModeSection(BaseModel):
    """``code_mode`` section of the UTCP adapter config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    defaults: UtcpOperatorCodeModeDefaults
    servers: dict[str, dict[str, Any]] = Field(min_length=1)


class UtcpMcpTemplateConfig(BaseModel):
    """MCP manual template config modeled from UTCP TypeScript SDK contracts."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    mcp_servers: dict[str, dict[str, Any]] = Field(
        alias="mcpServers",
        min_length=1,
    )


class UtcpManualCallTemplate(BaseModel):
    """One generic UTCP manual call template entry."""

    model_config = ConfigDict(frozen=True, extra="allow")

    name: str = ""
    call_template_type: str = Field(min_length=1)


class UtcpMcpManualCallTemplate(UtcpManualCallTemplate):
    """MCP-specific manual call template contract."""

    model_config = ConfigDict(frozen=True, extra="allow")

    call_template_type: Literal["mcp"]
    config: UtcpMcpTemplateConfig


class UtcpCodeModeConfig(BaseModel):
    """Top-level UTCP code-mode configuration document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    variables: dict[str, str] = Field(default_factory=dict)
    load_variables_from: tuple[dict[str, Any], ...] | None = None
    tool_repository: dict[str, Any] = Field(default_factory=dict)
    tool_search_strategy: dict[str, Any] = Field(default_factory=dict)
    post_processing: tuple[dict[str, Any], ...] = ()
    manual_call_templates: tuple[UtcpManualCallTemplate, ...] = ()


class UtcpMcpTemplateSummary(BaseModel):
    """Normalized MCP template summary used by service layer callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    server_names: tuple[str, ...]


class UtcpCodeModeLoadResult(BaseModel):
    """Result payload for one UTCP code-mode config load operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    config: UtcpCodeModeConfig
    mcp_templates: tuple[UtcpMcpTemplateSummary, ...]


class UtcpCodeModeHealthStatus(BaseModel):
    """UTCP code-mode adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class UtcpCodeModeAdapter(Protocol):
    """Protocol for loading UTCP code-mode config and MCP template metadata."""

    def health(self) -> UtcpCodeModeHealthStatus:
        """Probe UTCP code-mode adapter readiness."""

    def load(self) -> UtcpCodeModeLoadResult:
        """Build and validate UTCP config from inline settings."""
