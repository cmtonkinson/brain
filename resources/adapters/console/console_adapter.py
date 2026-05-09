"""In-process Console adapter implementation."""

from __future__ import annotations

import time
from threading import Lock

from lib.shared.envelope import EnvelopeMeta
from lib.shared.inbound_message import InboundMessage, InboundSender
from lib.shared.inbound_adapter import (
    InboundAdapterHealthResult,
    InboundCallback,
    InboundCallbackRegistrationResult,
    InboundCallbackResult,
)
from lib.shared.inbound_text import (
    parse_links,
    parse_slash_command,
    parse_text_approval,
)
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.console.adapter import (
    ConsoleAdapter,
    ConsoleAdapterInternalError,
    ConsoleInboundPayload,
)
from resources.adapters.console.component import RESOURCE_COMPONENT_ID
from resources.adapters.console.config import ConsoleAdapterSettings

_LOGGER = get_logger(__name__)


class InProcessConsoleAdapter(ConsoleAdapter):
    """Thin Console adapter that parses inbound payloads and dispatches to a callback."""

    def __init__(self, *, settings: ConsoleAdapterSettings) -> None:
        self._settings = settings
        self._lock = Lock()
        self._callback: InboundCallback | None = None

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def register_callback(
        self,
        *,
        callback: InboundCallback,
    ) -> InboundCallbackRegistrationResult:
        """Configure the in-process callback for inbound forwarding."""
        with self._lock:
            self._callback = callback
        return InboundCallbackRegistrationResult(
            registered=True,
            detail="configured",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def submit(
        self,
        *,
        meta: EnvelopeMeta,
        payload: ConsoleInboundPayload,
    ) -> InboundCallbackResult:
        """Forward one parsed Console payload to the registered callback."""
        with self._lock:
            callback = self._callback
        if callback is None:
            raise ConsoleAdapterInternalError(
                "console adapter has no registered callback"
            )
        message = InboundMessage(
            channel="console",
            sender=InboundSender(id="operator"),
            message_text=payload.message_text,
            timestamp_ms=int(time.time() * 1000),
            links=parse_links(payload.message_text),
            approval=parse_text_approval(payload.message_text),
            slash_command=parse_slash_command(payload.message_text),
            slash_authenticity=payload.slash_authenticity,
        )
        return callback(meta=meta, message=message)

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> InboundAdapterHealthResult:
        """Return adapter readiness."""
        with self._lock:
            callback_state = (
                "configured" if self._callback is not None else "unconfigured"
            )
        return InboundAdapterHealthResult(
            adapter_ready=True,
            detail=f"ready; callback={callback_state}",
        )
