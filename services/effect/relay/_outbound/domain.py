"""Domain payload contracts for Relay outbound service APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

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
    delivery_timestamp_ms: int | None = None
    notification: RoutedNotification | None = None


class ApprovalNotificationPayload(BaseModel):
    """Policy approval notification payload routed via Relay outbound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_token: str = Field(min_length=1)
    op_id: str = Field(min_length=1)
    op_version: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    invocation_id: str = Field(min_length=1)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime


class ApprovalCorrelationPayload(BaseModel):
    """Normalized AR->Policy correlation payload for approval matching."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str = Field(min_length=1)
    channel: str = Field(min_length=1)
    message_text: str = ""
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""


class ConsoleResponseMessage(BaseModel):
    """One outbound Brain response delivered to the console channel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str
    timestamp_ms: int


class HealthStatus(BaseModel):
    """Relay outbound and adapter readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    detail: str
