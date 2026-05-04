"""Transport-agnostic Console adapter protocol and DTOs.

The Console actor on the host posts inbound messages to Brain Core. The
*Console Adapter* is the T1 boundary that owns the wire-format parse and
forwards normalized payloads to the registered Relay inbound callback. The
adapter does not hold the slash-authenticity HMAC secret — Console mints on
the host and the proof flows through this adapter as opaque data.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.envelope import EnvelopeMeta


class ConsoleAdapterError(Exception):
    """Base exception for Console adapter failures."""


class ConsoleAdapterInternalError(ConsoleAdapterError):
    """Internal adapter failure (mapping or contract mismatch)."""


class ConsoleInboundPayload(BaseModel):
    """Normalized inbound payload from the Console actor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_text: str
    slash_authenticity: SlashAuthenticityProof | None = None


class ConsoleInboundCallbackResult(BaseModel):
    """Result returned by the Relay inbound callback."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queued: bool
    queue_name: str = ""


@runtime_checkable
class ConsoleInboundCallback(Protocol):
    """In-process callback invoked for one parsed Console payload."""

    def __call__(
        self,
        *,
        meta: EnvelopeMeta,
        payload: ConsoleInboundPayload,
    ) -> ConsoleInboundCallbackResult:
        """Handle one normalized Console payload and return the queueing result."""


class ConsoleCallbackRegistrationResult(BaseModel):
    """Result payload for in-process callback registration calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: bool
    detail: str


class ConsoleAdapterHealthResult(BaseModel):
    """Readiness payload for the Console adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_ready: bool
    detail: str


@runtime_checkable
class ConsoleAdapter(Protocol):
    """Protocol for Console inbound parsing and forwarding."""

    def register_callback(
        self,
        *,
        callback: ConsoleInboundCallback,
    ) -> ConsoleCallbackRegistrationResult:
        """Configure the in-process callback for inbound forwarding."""

    def submit(
        self,
        *,
        meta: EnvelopeMeta,
        payload: ConsoleInboundPayload,
    ) -> ConsoleInboundCallbackResult:
        """Forward one parsed Console payload to the registered callback."""

    def health(self) -> ConsoleAdapterHealthResult:
        """Return adapter health state."""
