"""Pydantic schema for the skill registry."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$"
)
CAPABILITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
FAILURE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillStatus(str, Enum):
    """Status markers for skill availability."""

    enabled = "enabled"
    disabled = "disabled"
    deprecated = "deprecated"


class AutonomyLevel(str, Enum):
    """Allowed autonomy tiers for skill execution."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class EntrypointRuntime(str, Enum):
    """Runtime options for skill entrypoints."""

    python = "python"
    mcp = "mcp"
    http = "http"
    script = "script"


class RateLimit(BaseModel):
    """Rate limit configuration for a skill."""
    model_config = ConfigDict(extra="forbid")

    max_per_minute: int = Field(..., ge=1)


class Entrypoint(BaseModel):
    """Runtime-specific entrypoint metadata for a skill."""
    model_config = ConfigDict(extra="forbid")

    runtime: EntrypointRuntime
    module: str | None = None
    handler: str | None = None
    tool: str | None = None
    url: str | None = None
    command: str | None = None

    @model_validator(mode="after")
    def _validate_runtime_fields(self) -> "Entrypoint":
        """Ensure the entrypoint includes required fields for its runtime."""
        if self.runtime == EntrypointRuntime.python:
            if not self.module or not self.handler:
                raise ValueError("python entrypoints require module and handler")
        if self.runtime == EntrypointRuntime.mcp:
            if not self.tool:
                raise ValueError("mcp entrypoints require tool")
        if self.runtime == EntrypointRuntime.http:
            if not self.url:
                raise ValueError("http entrypoints require url")
        if self.runtime == EntrypointRuntime.script:
            if not self.command:
                raise ValueError("script entrypoints require command")
        return self


class Redaction(BaseModel):
    """Redaction rules for skill inputs and outputs."""
    model_config = ConfigDict(extra="forbid")

    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)


class Deprecation(BaseModel):
    """Deprecation metadata for skills marked as deprecated."""
    model_config = ConfigDict(extra="forbid")

    deprecated: bool = True
    replaced_by: str | None = None
    removal_version: str | None = None

    @field_validator("removal_version")
    @classmethod
    def _validate_removal_version(cls, value: str | None) -> str | None:
        """Validate semver formatting for removal versions."""
        if value is None:
            return value
        if not SEMVER_RE.match(value):
            raise ValueError("removal_version must be semver")
        return value


class FailureMode(BaseModel):
    """Structured failure mode metadata for a skill."""
    model_config = ConfigDict(extra="forbid")

    code: str
    description: str
    retryable: bool = False

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        """Validate failure mode codes as snake_case."""
        if not FAILURE_CODE_RE.match(value):
            raise ValueError("failure mode code must be snake_case")
        return value


class SkillDefinition(BaseModel):
    """Schema for a single skill definition entry."""
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    status: SkillStatus = SkillStatus.enabled
    description: str
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    capabilities: list[str] = Field(..., min_length=1)
    side_effects: list[str] = Field(default_factory=list)
    autonomy: AutonomyLevel
    policy_tags: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    rate_limit: RateLimit | None = None
    entrypoint: Entrypoint
    redaction: Redaction | None = None
    deprecation: Deprecation | None = None
    failure_modes: list[FailureMode] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Validate skill names as snake_case."""
        if not SKILL_NAME_RE.match(value):
            raise ValueError("skill name must be snake_case")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Validate skill versions as semver."""
        if not SEMVER_RE.match(value):
            raise ValueError("version must be semver")
        return value

    @field_validator("capabilities", "side_effects")
    @classmethod
    def _validate_capabilities(cls, value: list[str]) -> list[str]:
        """Validate capability IDs against the registry format."""
        for cap_id in value:
            if not CAPABILITY_ID_RE.match(cap_id):
                raise ValueError(f"invalid capability ID: {cap_id}")
        return value

    @model_validator(mode="after")
    def _validate_constraints(self) -> "SkillDefinition":
        """Enforce cross-field constraints for a skill definition."""
        if self.side_effects:
            missing = [cap for cap in self.side_effects if cap not in self.capabilities]
            if missing:
                raise ValueError("side_effects must be a subset of capabilities")
        if self.status == SkillStatus.deprecated and self.deprecation is None:
            raise ValueError("deprecated skills must include deprecation metadata")
        codes = [mode.code for mode in self.failure_modes]
        if len(set(codes)) != len(codes):
            raise ValueError("failure mode codes must be unique")
        return self


class SkillRegistry(BaseModel):
    """Schema wrapper for the skill registry file."""
    model_config = ConfigDict(extra="forbid")

    registry_version: str
    skills: list[SkillDefinition]

    @field_validator("registry_version")
    @classmethod
    def _validate_registry_version(cls, value: str) -> str:
        """Validate registry versions as semver."""
        if not SEMVER_RE.match(value):
            raise ValueError("registry_version must be semver")
        return value
