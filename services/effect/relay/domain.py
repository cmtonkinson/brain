"""Public domain types for Relay Service.

Re-exports inbound and outbound payload types from the internal sub-packages
so callers depend only on ``services.effect.relay.domain``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from services.effect.relay._outbound.domain import (
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    ConsoleResponseMessage,
    HealthStatus as OutboundHealthStatus,
    RouteNotificationResult,
)
from services.effect.relay._inbound.domain import (
    ConsoleEnqueueResult,
    HealthStatus as InboundHealthStatus,
    IngestResult,
    NormalizedOperatorMessage,
    RegisterSignalCallbackResult,
)


class RelayHealthStatus(BaseModel):
    """Aggregated readiness across the Relay's inbound and outbound paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    inbound_ready: bool
    outbound_ready: bool
    adapter_ready: bool
    detail: str = "ok"


__all__ = [
    "ApprovalCorrelationPayload",
    "ApprovalNotificationPayload",
    "ConsoleEnqueueResult",
    "ConsoleResponseMessage",
    "InboundHealthStatus",
    "IngestResult",
    "NormalizedOperatorMessage",
    "OutboundHealthStatus",
    "RegisterSignalCallbackResult",
    "RelayHealthStatus",
    "RouteNotificationResult",
]
