"""Request validation models for Relay inbound service public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.inbound_message import InboundMessage


class IngestInboundMessageRequest(BaseModel):
    """Validate one normalized inbound message."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: InboundMessage


class PollOperatorInstructionRequest(BaseModel):
    """Validate one poll request for queued operator instructions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    wait_timeout_seconds: float = Field(default=0.0, ge=0.0)
