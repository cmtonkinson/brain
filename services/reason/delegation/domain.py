"""Domain types for Delegation Service."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class InvocationStatus(StrEnum):
    """Lifecycle states for one delegated subagent invocation."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceling = "canceling"
    canceled = "canceled"


class CancelReason(StrEnum):
    """Reasons one invocation may be terminated short of success."""

    manual = "manual"
    budget_tokens = "budget_tokens"
    budget_turns = "budget_turns"
    budget_wallclock = "budget_wallclock"
    parent_canceled = "parent_canceled"
    actor_lost = "actor_lost"


class InvocationRequest(BaseModel):
    """One delegated invocation request supplied by an op caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str = Field(min_length=1)
    context_text: str | None = None
    context_object_refs: tuple[str, ...] = ()
    personality_id: str = "subagent"
    tool_allowlist: tuple[str, ...] | None = None
    max_turns: int = Field(default=8, ge=1, le=64)
    budget_tokens: int | None = Field(default=None, ge=1)
    max_wallclock_seconds: int | None = Field(default=None, ge=1)
    parent_invocation_id: str | None = None


class InvocationStatusView(BaseModel):
    """Read-only state projection for one invocation row."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    status: InvocationStatus
    cancel_reason: CancelReason | None
    tokens_in: int
    tokens_out: int
    turn_count: int
    started_at: datetime | None
    completed_at: datetime | None


class InvocationStarted(BaseModel):
    """Result returned to the caller when an invocation has been queued."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str


class InvocationResult(BaseModel):
    """Terminal result for one invocation, returned by sync/wait callers."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    status: InvocationStatus
    final_response: str | None
    cancel_reason: CancelReason | None
    tokens_in: int
    tokens_out: int
    turn_count: int


class ClaimedInvocation(BaseModel):
    """One invocation handed to a Subagent Actor for execution."""

    model_config = ConfigDict(frozen=True)

    invocation_id: str
    parent_invocation_id: str | None
    principal: str
    channel: str
    personality_id: str
    prompt: str
    context_text: str | None
    context_object_refs: tuple[str, ...]
    tool_allowlist: tuple[str, ...] | None
    max_turns: int
    budget_tokens: int | None
    max_wallclock_seconds: int | None


class TurnDecision(BaseModel):
    """Result of one ``record_turn`` checkpoint evaluated by the service."""

    model_config = ConfigDict(frozen=True)

    should_stop: bool
    reason: CancelReason | None = None


class CancelOutcome(BaseModel):
    """Outcome of one cancel request."""

    model_config = ConfigDict(frozen=True)

    accepted: bool


class HealthStatus(BaseModel):
    """Delegation Service health snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    substrate_ready: bool
    detail: str = ""


__all__ = [
    "CancelOutcome",
    "CancelReason",
    "ClaimedInvocation",
    "HealthStatus",
    "InvocationRequest",
    "InvocationResult",
    "InvocationStarted",
    "InvocationStatus",
    "InvocationStatusView",
    "TurnDecision",
]
