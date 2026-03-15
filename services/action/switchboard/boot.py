"""Switchboard boot hooks for Signal adapter callback registration."""

from __future__ import annotations

from time import sleep

from packages.brain_core.boot import BootContext
from packages.brain_shared.envelope import Envelope, EnvelopeKind, new_meta
from packages.brain_shared.errors import codes, dependency_error, internal_error
from services.action.switchboard.component import SERVICE_COMPONENT_ID
from services.action.switchboard.config import (
    SwitchboardServiceSettings,
    resolve_switchboard_service_settings,
)
from services.action.switchboard.domain import RegisterSignalCallbackResult
from services.action.switchboard.service import SwitchboardService

dependencies: tuple[str, ...] = ("service_cache_authority",)


def _resolve_service_and_settings(
    ctx: BootContext,
) -> tuple[SwitchboardService, SwitchboardServiceSettings]:
    """Resolve Switchboard runtime service + settings from one boot context."""
    resolved = ctx.require_component(str(SERVICE_COMPONENT_ID))
    if not isinstance(resolved, SwitchboardService):
        raise RuntimeError(
            "boot context component 'service_switchboard' does not implement "
            "SwitchboardService"
        )
    settings = resolve_switchboard_service_settings(ctx.settings)
    return resolved, settings


def is_ready(ctx: BootContext) -> bool:
    """Return true once Switchboard and CAS report ready."""
    service, _settings = _resolve_service_and_settings(ctx)
    health = service.health(
        meta=new_meta(
            kind=EnvelopeKind.COMMAND,
            source="switchboard_boot",
            principal="switchboard",
        )
    )
    if not health.ok or health.payload is None:
        return False
    payload = health.payload.value
    return payload.service_ready and payload.cas_ready


def boot(ctx: BootContext) -> None:
    """Execute adapter callback registration during boot once readiness is satisfied."""
    service, settings = _resolve_service_and_settings(ctx)
    run_switchboard_boot_hook(
        service=service,
        settings=settings,
    )


def register_switchboard_callback_on_boot(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
    source: str = "switchboard_boot",
) -> Envelope[RegisterSignalCallbackResult]:
    """Register the in-process Signal callback once Switchboard and CAS are healthy."""
    attempts = settings.callback_register_max_retries + 1

    for attempt in range(attempts):
        health_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=source,
            principal="switchboard",
        )
        health = service.health(meta=health_meta)
        ready = (
            health.ok
            and health.payload is not None
            and health.payload.value.service_ready
            and health.payload.value.cas_ready
        )
        if ready:
            registration_meta = new_meta(
                kind=EnvelopeKind.COMMAND,
                source=source,
                principal="switchboard",
            )
            return service.register_signal_callback(meta=registration_meta)
        if attempt < settings.callback_register_max_retries:
            sleep(settings.callback_register_retry_delay_seconds)

    return Envelope[RegisterSignalCallbackResult](
        metadata=new_meta(
            kind=EnvelopeKind.RESULT,
            source=source,
            principal="switchboard",
        ),
        payload=None,
        errors=[
            dependency_error(
                "switchboard dependencies did not become ready before callback registration deadline",
                code=codes.DEPENDENCY_UNAVAILABLE,
            )
        ],
    )


def run_switchboard_boot_hook(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
) -> None:
    """Execute Switchboard callback registration hook and raise on failure."""
    result = register_switchboard_callback_on_boot(service=service, settings=settings)
    if result.ok:
        return
    messages = "; ".join(error.message for error in result.errors) or "unknown"
    raise RuntimeError(
        internal_error(
            f"switchboard boot hook failed: {messages}",
            code=codes.INTERNAL_ERROR,
        ).message
    )
