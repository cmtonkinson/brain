"""Domain contracts for Capability Engine manifest and invocation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


from services.action.capability_engine.schema import expand_schema


class CapabilityInvocationMetadata(BaseModel):
    """Invocation metadata supplied by CES callers for policy and auditing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    source: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    parent_invocation_id: str = ""
    confirmed: bool = False
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""
    message_text: str = ""


class CapabilityInvokeResult(BaseModel):
    """Output payload returned by CES invoke operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    capability_version: str
    output: dict[str, Any] | None = None
    policy_decision_id: str
    policy_regime_id: str
    policy_allowed: bool
    policy_reason_codes: tuple[str, ...]
    policy_obligations: tuple[str, ...]
    proposal_token: str = ""


class CapabilityEngineHealthStatus(BaseModel):
    """Capability Engine health payload and registry counters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    policy_ready: bool
    discovered_capabilities: int
    invocation_audit_rows: int
    detail: str


class CapabilityExecutionResponse(BaseModel):
    """Internal execution result type used by runtime handlers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    output: dict[str, Any] | None = None


class PipelineStep(BaseModel):
    """One pipeline step, optionally with explicit input remapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    input_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_input_mapping(self) -> PipelineStep:
        """Require non-empty consumer and producer field names."""
        for consumer_field, producer_field in self.input_mapping.items():
            if not consumer_field:
                raise ValueError(
                    "pipeline input_mapping consumer fields must be non-empty"
                )
            if not producer_field:
                raise ValueError(
                    "pipeline input_mapping producer fields must be non-empty"
                )
        return self

    @classmethod
    def from_entry(cls, entry: str | PipelineStep) -> PipelineStep:
        """Normalize one pipeline entry to the object form."""
        if isinstance(entry, cls):
            return entry
        return cls(capability=entry)


class CapabilityManifestBase(BaseModel):
    """Immutable capability manifest metadata shared by ops and skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: str
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    summary: str = Field(min_length=1)
    enabled: bool = True
    autonomy: int = Field(default=0, ge=0)
    requires_approval: bool = False
    side_effects: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    simple_output_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _expand_manifest_schemas(cls, value: Any) -> Any:
        """Expand manifest schema shorthand with kind-specific alias rules."""
        if not isinstance(value, dict):
            return value

        expanded = dict(value)
        allow_field_aliases = expanded.get("kind") == "pipeline_skill"

        for schema_field in ("input_schema", "output_schema"):
            expanded[schema_field] = expand_schema(
                expanded.get(schema_field),
                allow_field_aliases=allow_field_aliases,
            )
        return expanded


class OpCapabilityManifest(CapabilityManifestBase):
    """Manifest schema for an Op capability package."""

    kind: Literal["native_op", "mcp_op"]
    call_target: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_required_capabilities(self) -> OpCapabilityManifest:
        """Reject explicit sub-capability dependencies for thin op wrappers."""
        if self.required_capabilities:
            raise ValueError("required_capabilities is only allowed for logic skills")
        return self


class SkillCapabilityManifest(CapabilityManifestBase):
    """Manifest schema for a Skill capability package."""

    kind: Literal["logic_skill", "pipeline_skill"]
    pipeline: tuple[str | PipelineStep, ...] = ()
    entrypoint: str = "execute.py"

    @model_validator(mode="after")
    def _validate_required_capabilities(self) -> SkillCapabilityManifest:
        """Allow required_capabilities only for non-declarative logic skills."""
        if self.kind == "pipeline_skill" and self.required_capabilities:
            raise ValueError("required_capabilities is only allowed for logic skills")
        return self


CapabilityManifest = OpCapabilityManifest | SkillCapabilityManifest


class CapabilityPolicySummary(BaseModel):
    """Policy decision summary included in CES responses and audit entries."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    policy_regime_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    obligations: tuple[str, ...]
    proposal_token: str = ""


class CapabilityDescriptor(BaseModel):
    """Agent-facing descriptor for one registered capability.

    Contains everything an L2 agent needs to A) present the capability as an
    LLM tool call and B) construct a valid ``invoke_capability`` call if the
    LLM selects it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    kind: str
    version: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    simple_output_path: str | None
    autonomy: int
    requires_approval: bool
    side_effects: tuple[str, ...]
    required_capabilities: tuple[str, ...]


class CapabilitySearchHit(BaseModel):
    """Compact discovery result for one semantically matched capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    required_params: tuple[str, ...]
    summary: str


class CapabilityDiscoveryStateRow(BaseModel):
    """Durable CES-owned state for one indexed capability discovery document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    content_digest: str
    chunk_ordinal: int


class CapabilityInvocationAuditRow(BaseModel):
    """Append-only invocation audit record owned by Capability Engine Service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audit_id: str
    envelope_id: str
    trace_id: str
    parent_id: str
    invocation_id: str
    parent_invocation_id: str
    actor: str
    source: str
    channel: str
    capability_id: str
    capability_version: str
    policy_decision_id: str
    policy_regime_id: str
    allowed: bool
    reason_codes: tuple[str, ...]
    proposal_token: str
    created_at: datetime
