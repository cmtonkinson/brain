"""Domain contracts for Policy Service authorization and approval workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.envelope import EnvelopeMeta
from packages.brain_shared.errors import ErrorDetail

APPROVAL_REQUIRED_OBLIGATION = "approval_required"
UNKNOWN_CALL_TARGET_REASON = "unknown_call_target"


class CapabilityPolicyInput(BaseModel):
    """Capability metadata evaluated by Policy Service for one invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1)
    kind: Literal["skill", "op"]
    version: str = Field(min_length=1)
    autonomy: int = Field(default=0, ge=0)
    requires_approval: bool = False
    side_effects: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()


class InvocationPolicyInput(BaseModel):
    """Invocation metadata for policy evaluation and approval correlation."""

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


class CapabilityInvocationRequest(BaseModel):
    """Normalized policy input contract for one capability invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: EnvelopeMeta
    capability: CapabilityPolicyInput
    invocation: InvocationPolicyInput
    input_payload: dict[str, Any]


class PolicyRule(BaseModel):
    """One effective policy rule scoped to a specific capability identifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = True
    autonomy_ceiling: int | None = Field(default=None, ge=0)
    actors_allow: tuple[str, ...] = ()
    actors_deny: tuple[str, ...] = ()
    channels_allow: tuple[str, ...] = ()
    channels_deny: tuple[str, ...] = ()
    require_approval: bool | None = None


class PolicyRuleOverlay(BaseModel):
    """Overlay patch for mutable operational rule controls only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool | None = None
    autonomy_ceiling: int | None = Field(default=None, ge=0)
    actors_allow: tuple[str, ...] | None = None
    actors_deny: tuple[str, ...] | None = None
    channels_allow: tuple[str, ...] | None = None
    channels_deny: tuple[str, ...] | None = None
    require_approval: bool | None = None


class PolicyDocument(BaseModel):
    """Base or effective policy document evaluated by Policy Service."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    rules: dict[str, PolicyRule] = Field(default_factory=dict)


class PolicyOverlay(BaseModel):
    """Named overlay used to mutate mutable operational policy fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    unset: tuple[str, ...] = ()
    rules: dict[str, PolicyRuleOverlay] = Field(default_factory=dict)


class PolicyRegimeSnapshot(BaseModel):
    """Append-only persisted effective-policy snapshot keyed by deterministic hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_regime_id: str
    policy_hash: str
    policy_json: str
    policy_id: str
    policy_version: str
    created_at: datetime


class ActivePolicyRegimePointer(BaseModel):
    """Single-row pointer to the currently active effective policy regime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pointer_id: str = "active"
    policy_regime_id: str


class PolicyDecision(BaseModel):
    """Structured policy decision record for one evaluated request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
    policy_regime_id: str
    policy_regime_hash: str
    allowed: bool
    reason_codes: tuple[str, ...]
    obligations: tuple[str, ...]
    policy_metadata: dict[str, str]
    decided_at: datetime
    policy_name: str
    policy_version: str


class ApprovalProposal(BaseModel):
    """Approval proposal artifact emitted for approval-required decisions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_token: str
    proposal_version: str = "v1"
    capability_id: str
    capability_version: str
    summary: str
    actor: str
    channel: str
    trace_id: str
    invocation_id: str
    policy_regime_id: str
    created_at: datetime
    expires_at: datetime
    clarification_attempts: int = 0


class ApprovalNotificationPayload(BaseModel):
    """Token-only PS->AR approval notification contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_token: str
    capability_id: str
    capability_version: str
    summary: str
    actor: str
    channel: str
    trace_id: str
    invocation_id: str
    expires_at: datetime


class ApprovalCorrelationPayload(BaseModel):
    """AR->PS correlation payload for deterministic approval matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    message_text: str = ""
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""


class PolicyExecutionResult(BaseModel):
    """In-process result contract returned by policy wrapper execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    output: dict[str, Any] | None = None
    errors: tuple[ErrorDetail, ...] = ()
    decision: PolicyDecision
    proposal: ApprovalProposal | None = None


class PolicyHealthStatus(BaseModel):
    """Health payload and in-memory counters for Policy Service runtime state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    active_policy_regime_id: str
    regime_rows: int
    decision_log_rows: int
    proposal_rows: int
    dedupe_rows: int
    detail: str


class PolicyDecisionLogRow(BaseModel):
    """Append-only audit row for one policy decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: PolicyDecision
    metadata: EnvelopeMeta
    actor: str
    channel: str
    capability_id: str


class PolicyApprovalProposalRow(BaseModel):
    """Append-only audit row for one approval proposal state record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal: ApprovalProposal
    status: Literal["pending", "approved", "expired", "rejected"]


class PolicyDedupeLogRow(BaseModel):
    """Append-only audit row for dedupe checks keyed by envelope id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dedupe_key: str
    envelope_id: str
    trace_id: str
    denied: bool
    window_seconds: int
    created_at: datetime


def utc_now() -> datetime:
    """Return current UTC timestamp for policy timestamps."""
    return datetime.now(UTC)
