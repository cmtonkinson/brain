"""Transport-agnostic Signal adapter protocol and DTOs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class SignalAdapterError(Exception):
    """Base exception for Signal adapter failures."""


class SignalAdapterDependencyError(SignalAdapterError):
    """Dependency-level adapter failure (network/upstream unavailable)."""


class SignalAdapterInternalError(SignalAdapterError):
    """Internal adapter failure (mapping or contract mismatch)."""


class SignalInboundCallbackResult(BaseModel):
    """Result payload returned by one in-process inbound callback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    queued: bool
    reason: str
    sender_e164: str = ""
    timestamp_ms: int | None = None


@runtime_checkable
class SignalInboundCallback(Protocol):
    """In-process callback invoked for one raw Signal receive payload."""

    def __call__(self, *, raw_body_json: str) -> SignalInboundCallbackResult:
        """Handle one raw inbound Signal payload and return the queueing result."""


class SignalCallbackRegistrationResult(BaseModel):
    """Result payload for in-process callback registration calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class SignalAdapterHealthResult(BaseModel):
    """Readiness payload for Signal adapter dependencies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


class SignalSendMessageResult(BaseModel):
    """Result payload for outbound Signal message delivery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delivered: bool
    recipient_e164: str
    sender_e164: str
    detail: str
    sent_timestamp_ms: int | None = None


@runtime_checkable
class SignalAdapter(Protocol):
    """Protocol for Signal inbound callback registration and health checks."""

    def register_callback(
        self,
        *,
        callback: SignalInboundCallback,
    ) -> SignalCallbackRegistrationResult:
        """Configure one in-process callback for inbound Signal forwarding."""

    def health(self) -> SignalAdapterHealthResult:
        """Return adapter health state."""

    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        """Send one outbound Signal message via configured runtime."""
