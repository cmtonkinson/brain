"""Domain payload contracts for Relay inbound service APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from lib.shared.inbound_message import InboundMessage


class IngestResult(BaseModel):
    """Ingress decision payload describing acceptance and queueing outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    queued: bool
    queue_name: str
    reason: str
    message: InboundMessage | None = None


class RegisterInboundCallbacksResult(BaseModel):
    """Adapter callback-registration operation result payload."""

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
