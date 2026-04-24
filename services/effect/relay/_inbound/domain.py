"""Domain payload contracts for Relay inbound service APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class NormalizedOperatorMessage(BaseModel):
    """Normalized inbound operator message payload for downstream processing.

    Required fields (``source``, ``message_text``, ``timestamp_ms``) are
    channel-agnostic.  Signal-specific fields default to empty/``None`` so that
    non-Signal channels (e.g. console) can produce valid instances without
    synthesizing placeholder values.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    message_text: str
    timestamp_ms: int
    sender_e164: str = ""
    source_device: str = ""
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
    message: NormalizedOperatorMessage | None = None


class ConsoleEnqueueResult(BaseModel):
    """Result payload for console message ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queued: bool
    queue_name: str


class RegisterSignalCallbackResult(BaseModel):
    """Signal adapter callback-registration operation result payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class HealthStatus(BaseModel):
    """Relay inbound and dependency readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    adapter_ready: bool
    cas_ready: bool
    detail: str
