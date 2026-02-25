"""Transport-agnostic UTCP code-mode adapter contracts and DTOs."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class UtcpCodeModeAdapterError(Exception):
    """Base exception for UTCP code-mode adapter failures."""


class UtcpCodeModeConfigNotFoundError(UtcpCodeModeAdapterError):
    """UTCP config file path does not exist."""


class UtcpCodeModeConfigReadError(UtcpCodeModeAdapterError):
    """UTCP config file could not be read from disk."""


class UtcpCodeModeConfigParseError(UtcpCodeModeAdapterError):
    """UTCP source config file is not valid YAML."""


class UtcpCodeModeConfigSchemaError(UtcpCodeModeAdapterError):
    """UTCP source or generated config does not satisfy expected schema."""


class UtcpOperatorCodeModeDefaults(BaseModel):
    """Operator YAML defaults for UTCP code-mode source config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    call_template_type: Literal["mcp"]


class UtcpOperatorCodeModeSection(BaseModel):
    """Operator YAML ``code_mode`` section used to derive UTCP config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    defaults: UtcpOperatorCodeModeDefaults
    servers: dict[str, dict[str, Any]] = Field(min_length=1)


class UtcpOperatorYamlConfig(BaseModel):
    """Operator UTCP YAML schema (source format) consumed by this adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code_mode: UtcpOperatorCodeModeSection


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
    generated_json_path: str


class UtcpCodeModeAdapter(Protocol):
    """Protocol for loading UTCP code-mode config and MCP template metadata."""

    def load(self) -> UtcpCodeModeLoadResult:
        """Load and validate UTCP config from local disk."""
