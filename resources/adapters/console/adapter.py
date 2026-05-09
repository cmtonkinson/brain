"""Transport-agnostic Console adapter protocol and DTOs.

The Console actor on the host posts inbound messages to Brain Core. The
*Console Adapter* is the T1 boundary that owns the wire-format parse and
forwards normalized payloads to the registered inbound callback. The adapter
does not hold the slash-authenticity HMAC secret; Console mints on the host and
the proof flows through this adapter as opaque data.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.envelope import EnvelopeMeta
from lib.shared.inbound_adapter import (
    InboundAdapterHealthResult,
    InboundAdapterInternalError,
    InboundCallback,
    InboundCallbackRegistrationResult,
    InboundCallbackResult,
)


class ConsoleAdapterError(InboundAdapterInternalError):
    """Base exception for Console adapter failures."""


class ConsoleAdapterInternalError(ConsoleAdapterError):
    """Internal adapter failure (mapping or contract mismatch)."""


class ConsoleInboundPayload(BaseModel):
    """Normalized inbound payload from the Console actor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message_text: str
    slash_authenticity: SlashAuthenticityProof | None = None


@runtime_checkable
class ConsoleAdapter(Protocol):
    """Protocol for Console inbound parsing and forwarding."""

    def register_callback(
        self,
        *,
        callback: InboundCallback,
    ) -> InboundCallbackRegistrationResult:
        """Configure the in-process callback for inbound forwarding."""
        ...

    def submit(
        self,
        *,
        meta: EnvelopeMeta,
        payload: ConsoleInboundPayload,
    ) -> InboundCallbackResult:
        """Forward one parsed Console payload to the registered callback."""
        ...

    def health(self) -> InboundAdapterHealthResult:
        """Return adapter health state."""
        ...
