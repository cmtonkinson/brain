"""Transport-agnostic Signal adapter protocol and DTOs."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.inbound_adapter import (
    InboundAdapterDependencyError,
    InboundAdapterHealthResult,
    InboundAdapterInternalError,
    InboundCallback,
    InboundCallbackRegistrationResult,
)


class SignalAdapterError(InboundAdapterInternalError):
    """Base exception for Signal adapter failures."""


class SignalAdapterDependencyError(InboundAdapterDependencyError):
    """Dependency-level adapter failure (network/upstream unavailable)."""


class SignalAdapterInternalError(InboundAdapterInternalError):
    """Internal adapter failure (mapping or contract mismatch)."""


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
    """Protocol for Signal adapter inbound, health, and outbound operations."""

    def register_callback(
        self,
        *,
        callback: InboundCallback,
    ) -> InboundCallbackRegistrationResult:
        """Configure one in-process callback for inbound forwarding."""
        ...

    def health(self) -> InboundAdapterHealthResult:
        """Return adapter health state."""
        ...

    def send_message(
        self,
        *,
        sender_e164: str,
        recipient_e164: str,
        message: str,
    ) -> SignalSendMessageResult:
        """Send one outbound Signal message via configured runtime."""
        ...

    def mint_slash_authenticity_proof(
        self,
        *,
        channel: str,
        message_text: str,
    ) -> SlashAuthenticityProof:
        """Sign one operator-channel slash command with the local HMAC secret.

        Callers must already have confirmed the message originated from the
        operator's identity. The Adapter holds the secret; the Relay does
        not see it.
        """
        ...
