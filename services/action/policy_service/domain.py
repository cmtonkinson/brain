"""Domain contracts for Policy Service authorization workflows."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.envelope import EnvelopeMeta
from packages.brain_shared.errors import ErrorDetail

APPROVAL_REQUIRED_OBLIGATION = "approval_required"


class CapabilityRef(BaseModel):
    """Canonical identity for one capability invocation target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["skill", "op"]
    namespace: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(default="", min_length=0)

    @property
    def capability_id(self) -> str:
        """Return stable capability-id string used in policy checks."""
        version = self.version or "latest"
        return f"{self.kind}:{self.namespace}:{self.name}:{version}"


class PolicyContext(BaseModel):
    """Runtime policy context supplied by capability callers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    allowed_capabilities: tuple[str, ...] = ()
    max_autonomy: int | None = None
    confirmed: bool = False
    approval_token: str = ""
    invocation_id: str = Field(min_length=1)
    parent_invocation_id: str = ""


class CapabilityInvocationRequest(BaseModel):
    """Normalized policy input contract for one capability invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: EnvelopeMeta
    capability: CapabilityRef
    input_payload: dict[str, Any]
    policy_context: PolicyContext
    declared_autonomy: int = Field(default=0, ge=0)
    requires_approval: bool = False


class PolicyDecision(BaseModel):
    """Structured policy decision record for one evaluated request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_id: str
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

    proposal_id: str
    proposal_version: str = "v1"
    action_kind: Literal["skill", "op"]
    action_name: str
    action_version: str
    autonomy: int
    required_capabilities: tuple[str, ...]
    reason_for_review: str
    actor: str
    channel: str
    trace_id: str
    invocation_id: str
    created_at: datetime
    expires_at: datetime


class PolicyExecutionResult(BaseModel):
    """In-process result contract returned by policy wrapper execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    output: dict[str, Any] | None = None
    errors: tuple[ErrorDetail, ...] = ()
    decision: PolicyDecision
    proposal: ApprovalProposal | None = None


class PolicyHealthStatus(BaseModel):
    """Health and in-memory audit counters for Policy Service runtime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
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
