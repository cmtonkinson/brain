"""Domain payload contracts for Attention Router Service APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RoutedNotification(BaseModel):
    """Canonical notification payload after routing normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str
    channel: str
    recipient: str
    sender: str
    message: str
    title: str
    dedupe_key: str = ""
    batch_key: str = ""


class RouteNotificationResult(BaseModel):
    """Outcome of one notification routing decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: str
    delivered: bool
    detail: str
    suppressed_reason: str = ""
    batched_count: int = 0
    notification: RoutedNotification | None = None


class ApprovalNotificationPayload(BaseModel):
    """Token-only policy approval notification payload routed via Attention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_token: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    capability_version: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    expires_at: datetime


class ApprovalCorrelationPayload(BaseModel):
    """Normalized AR->PS correlation payload for approval matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    message_text: str = ""
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""


class HealthStatus(BaseModel):
    """Attention Router and adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    detail: str
