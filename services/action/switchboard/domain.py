"""Domain payload contracts for Switchboard Service APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NormalizedSignalMessage(BaseModel):
    """Normalized inbound Signal message payload for downstream processing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sender_e164: str
    message_text: str
    timestamp_ms: int
    source_device: str
    source: str
    group_id: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reaction_emoji: str | None = None
    approval_intent: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


class IngestResult(BaseModel):
    """Ingress decision payload describing acceptance and queueing outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    queued: bool
    queue_name: str
    reason: str
    message: NormalizedSignalMessage | None = None


class RegisterSignalCallbackResult(BaseModel):
    """Signal adapter callback-registration operation result payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class HealthStatus(BaseModel):
    """Switchboard and dependency readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    cas_ready: bool
    detail: str
