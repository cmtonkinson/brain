"""Relay boot hook: register inbound adapter callbacks once inbound is healthy."""

from __future__ import annotations

import logging
from time import sleep

from lib.core.boot import BootContext
from lib.shared.envelope import EnvelopeKind, new_meta
from lib.shared.errors import codes, internal_error
from services.effect.relay.component import SERVICE_COMPONENT_ID
from services.effect.relay.config import (
    RelayServiceSettings,
    resolve_relay_settings,
)
from services.effect.relay.service import RelayService

dependencies: tuple[str, ...] = ("service_cache",)

_LOGGER = logging.getLogger(__name__)
_SOURCE = "relay_boot"
_PRINCIPAL = "service_relay"


def _resolve(ctx: BootContext) -> tuple[RelayService, RelayServiceSettings]:
    """Resolve Relay service and settings from one boot context."""
    resolved = ctx.require_component(str(SERVICE_COMPONENT_ID))
    if not isinstance(resolved, RelayService):
        raise RuntimeError(
            f"boot context component '{SERVICE_COMPONENT_ID}' does not implement "
            "RelayService"
        )
    return resolved, resolve_relay_settings(ctx.settings)


def _is_inbound_ready(service: RelayService) -> bool:
    """Return True when Relay's inbound path reports ready."""
    health = service.health(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND,
            source=_SOURCE,
            principal=_PRINCIPAL,
        )
    )
    if not health.ok or health.payload is None:
        return False
    payload = health.payload.value
    return payload.service_ready and payload.inbound_ready


def is_ready(ctx: BootContext) -> bool:
    """Return True once Relay inbound dependencies are healthy."""
    service, _settings = _resolve(ctx)
    return _is_inbound_ready(service)


def boot(ctx: BootContext) -> None:
    """Register in-process inbound adapter callbacks once Relay is ready."""
    service, settings = _resolve(ctx)
    inbound_settings = settings.inbound
    attempts = inbound_settings.callback_register_max_retries + 1

    for attempt in range(attempts):
        if _is_inbound_ready(service):
            registration_meta = new_meta(
                kind=EnvelopeKind.COMMAND,
                source=_SOURCE,
                principal=_PRINCIPAL,
            )
            result = service.register_inbound_callbacks(meta=registration_meta)
            if result.ok:
                return
            messages = "; ".join(error.message for error in result.errors) or "unknown"
            raise RuntimeError(
                internal_error(
                    f"relay boot hook failed: {messages}",
                    code=codes.INTERNAL_ERROR,
                ).message
            )
        if attempt < inbound_settings.callback_register_max_retries:
            sleep(inbound_settings.callback_register_retry_delay_seconds)

    raise RuntimeError(
        internal_error(
            "relay boot hook failed: dependencies did not become ready before deadline",
            code=codes.INTERNAL_ERROR,
        ).message
    )
