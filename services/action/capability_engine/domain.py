"""Domain contracts for Capability Engine manifest and invocation APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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


class CapabilityManifestBase(BaseModel):
    """Immutable capability manifest metadata shared by ops and skills."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    kind: Literal["skill", "op"]
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    summary: str = Field(min_length=1)
    enabled: bool = True
    autonomy: int = Field(default=0, ge=0)
    requires_approval: bool = False
    side_effects: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    input_types: tuple[str, ...] = Field(default=("json",), min_length=1)
    output_types: tuple[str, ...] = Field(default=("json",), min_length=1)


class OpCapabilityManifest(CapabilityManifestBase):
    """Manifest schema for an Op capability package."""

    kind: Literal["op"]
    call_target: str = Field(min_length=1)


class SkillCapabilityManifest(CapabilityManifestBase):
    """Manifest schema for a Skill capability package."""

    kind: Literal["skill"]
    skill_type: Literal["logic", "pipeline"]
    pipeline: tuple[str, ...] = ()
    entrypoint: str = "execute.py"


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
    kind: Literal["skill", "op"]
    version: str
    summary: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    autonomy: int
    requires_approval: bool
    side_effects: tuple[str, ...]
    required_capabilities: tuple[str, ...]


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
