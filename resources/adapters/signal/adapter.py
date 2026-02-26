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


class SignalWebhookRegistrationResult(BaseModel):
    """Result payload for webhook registration calls."""

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


@runtime_checkable
class SignalAdapter(Protocol):
    """Protocol for Signal webhook registration and health checks."""

    def register_webhook(
        self,
        *,
        callback_url: str,
        shared_secret: str,
    ) -> SignalWebhookRegistrationResult:
        """Configure callback URL/secret for inbound webhook forwarding."""

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
