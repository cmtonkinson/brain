"""Pydantic schema for skill and op registries."""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)" r"(?:-[0-9A-Za-z-.]+)?(?:\+[0-9A-Za-z-.]+)?$"
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
    """Allowed autonomy tiers for execution."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class EntrypointRuntime(str, Enum):
    """Runtime options for logic skill entrypoints."""

    python = "python"
    http = "http"
    script = "script"


class OpRuntime(str, Enum):
    """Runtime options for op execution."""

    native = "native"
    mcp = "mcp"
    http = "http"
    script = "script"


class SkillKind(str, Enum):
    """Skill kinds supported by the v2 framework."""

    logic = "logic"
    pipeline = "pipeline"


class CallTargetKind(str, Enum):
    """Call target kinds for skills and pipeline steps."""

    skill = "skill"
    op = "op"


class RateLimit(BaseModel):
    """Rate limit configuration for a registry entry."""

    model_config = ConfigDict(extra="forbid")

    max_per_minute: int = Field(..., ge=1)


class Entrypoint(BaseModel):
    """Runtime-specific entrypoint metadata for a logic skill."""

    model_config = ConfigDict(extra="forbid")

    runtime: EntrypointRuntime
    module: str | None = None
    handler: str | None = None
    url: str | None = None
    command: str | None = None

    @model_validator(mode="after")
    def _validate_runtime_fields(self) -> "Entrypoint":
        """Ensure the entrypoint includes required fields for its runtime."""
        if self.runtime == EntrypointRuntime.python:
            if not self.module or not self.handler:
                raise ValueError("python entrypoints require module and handler")
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


class CallTargetRef(BaseModel):
    """Reference to a skill or op by name and optional version."""

    model_config = ConfigDict(extra="forbid")

    kind: CallTargetKind
    name: str
    version: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_target_name(cls, value: str) -> str:
        """Validate target names as snake_case."""
        if not SKILL_NAME_RE.match(value):
            raise ValueError("call target name must be snake_case")
        return value

    @field_validator("version")
    @classmethod
    def _validate_target_version(cls, value: str | None) -> str | None:
        """Validate target versions as semver when provided."""
        if value is None:
            return value
        if not SEMVER_RE.match(value):
            raise ValueError("call target version must be semver")
        return value


class PipelineStep(BaseModel):
    """Single pipeline step definition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    target: CallTargetRef
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _validate_step_id(cls, value: str) -> str:
        """Validate pipeline step identifiers as snake_case."""
        if not SKILL_NAME_RE.match(value):
            raise ValueError("pipeline step id must be snake_case")
        return value


class BaseSkillDefinition(BaseModel):
    """Common schema fields for all skills."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str
    status: SkillStatus = SkillStatus.enabled
    description: str
    kind: SkillKind
    inputs_schema: dict[str, Any]
    outputs_schema: dict[str, Any]
    capabilities: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    autonomy: AutonomyLevel
    policy_tags: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    rate_limit: RateLimit | None = None
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
    def _validate_constraints(self) -> "BaseSkillDefinition":
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


class LogicSkillDefinition(BaseSkillDefinition):
    """Schema for logic skill definitions."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[SkillKind.logic]
    entrypoint: Entrypoint
    call_targets: list[CallTargetRef] = Field(..., min_length=1)


class PipelineSkillDefinition(BaseSkillDefinition):
    """Schema for pipeline skill definitions."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[SkillKind.pipeline]
    steps: list[PipelineStep] = Field(..., min_length=1)


SkillDefinition = Annotated[
    Union[LogicSkillDefinition, PipelineSkillDefinition],
    Field(discriminator="kind"),
]


class OpDefinition(BaseModel):
    """Schema for a single op definition entry."""

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
    runtime: OpRuntime
    module: str | None = None
    handler: str | None = None
    tool: str | None = None
    url: str | None = None
    command: str | None = None
    redaction: Redaction | None = None
    deprecation: Deprecation | None = None
    failure_modes: list[FailureMode] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        """Validate op names as snake_case."""
        if not SKILL_NAME_RE.match(value):
            raise ValueError("op name must be snake_case")
        return value

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: str) -> str:
        """Validate op versions as semver."""
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
    def _validate_constraints(self) -> "OpDefinition":
        """Enforce cross-field constraints for an op definition."""
        if self.side_effects:
            missing = [cap for cap in self.side_effects if cap not in self.capabilities]
            if missing:
                raise ValueError("side_effects must be a subset of capabilities")
        if self.status == SkillStatus.deprecated and self.deprecation is None:
            raise ValueError("deprecated ops must include deprecation metadata")
        codes = [mode.code for mode in self.failure_modes]
        if len(set(codes)) != len(codes):
            raise ValueError("failure mode codes must be unique")
        if self.runtime == OpRuntime.native:
            if not self.module or not self.handler:
                raise ValueError("native ops require module and handler")
        if self.runtime == OpRuntime.mcp:
            if not self.tool:
                raise ValueError("mcp ops require tool")
        if self.runtime == OpRuntime.http:
            if not self.url:
                raise ValueError("http ops require url")
        if self.runtime == OpRuntime.script:
            if not self.command:
                raise ValueError("script ops require command")
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


class OpRegistry(BaseModel):
    """Schema wrapper for the op registry file."""

    model_config = ConfigDict(extra="forbid")

    registry_version: str
    ops: list[OpDefinition]

    @field_validator("registry_version")
    @classmethod
    def _validate_registry_version(cls, value: str) -> str:
        """Validate registry versions as semver."""
        if not SEMVER_RE.match(value):
            raise ValueError("registry_version must be semver")
        return value
