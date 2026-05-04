"""In-process Console adapter implementation."""

from __future__ import annotations

from threading import Lock

from lib.shared.envelope import EnvelopeMeta
from lib.shared.logging import get_logger, public_api_instrumented
from resources.adapters.console.adapter import (
    ConsoleAdapter,
    ConsoleAdapterHealthResult,
    ConsoleAdapterInternalError,
    ConsoleCallbackRegistrationResult,
    ConsoleInboundCallback,
    ConsoleInboundCallbackResult,
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
        self._callback: ConsoleInboundCallback | None = None

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def register_callback(
        self,
        *,
        callback: ConsoleInboundCallback,
    ) -> ConsoleCallbackRegistrationResult:
        """Configure the in-process callback for inbound forwarding."""
        with self._lock:
            self._callback = callback
        return ConsoleCallbackRegistrationResult(
            registered=True,
            detail="configured",
        )

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def submit(
        self,
        *,
        meta: EnvelopeMeta,
        payload: ConsoleInboundPayload,
    ) -> ConsoleInboundCallbackResult:
        """Forward one parsed Console payload to the registered callback."""
        with self._lock:
            callback = self._callback
        if callback is None:
            raise ConsoleAdapterInternalError(
                "console adapter has no registered callback"
            )
        return callback(meta=meta, payload=payload)

    @public_api_instrumented(logger=_LOGGER, component_id=str(RESOURCE_COMPONENT_ID))
    def health(self) -> ConsoleAdapterHealthResult:
        """Return adapter readiness."""
        with self._lock:
            callback_state = (
                "configured" if self._callback is not None else "unconfigured"
            )
        return ConsoleAdapterHealthResult(
            adapter_ready=True,
            detail=f"ready; callback={callback_state}",
        )
