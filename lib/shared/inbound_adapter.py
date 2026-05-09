"""Shared in-process contract for inbound operator-message adapters."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from lib.shared.envelope import EnvelopeMeta
from lib.shared.inbound_message import InboundMessage


class InboundAdapterError(Exception):
    """Base exception for inbound adapter failures."""


class InboundAdapterDependencyError(InboundAdapterError):
    """Dependency-level inbound adapter failure."""


class InboundAdapterInternalError(InboundAdapterError):
    """Internal inbound adapter failure."""


class InboundCallbackResult(BaseModel):
    """Result returned after one normalized inbound message is forwarded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    accepted: bool
    queued: bool
    reason: str
    queue_name: str = ""
    sender_e164: str | None = None
    timestamp_ms: int | None = None


@runtime_checkable
class InboundCallback(Protocol):
    """In-process callback invoked for one normalized inbound message."""

    def __call__(
        self,
        *,
        meta: EnvelopeMeta,
        message: InboundMessage,
    ) -> InboundCallbackResult:
        """Handle one normalized inbound message and return the queueing result."""
        ...


class InboundCallbackRegistrationResult(BaseModel):
    """Result payload for in-process callback registration calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class InboundAdapterHealthResult(BaseModel):
    """Readiness payload for an inbound adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


@runtime_checkable
class InboundCallbackRegistrar(Protocol):
    """Protocol for adapters that forward normalized inbound messages."""

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
