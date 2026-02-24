"""Switchboard boot hooks for webhook callback registration."""

from __future__ import annotations

from time import sleep
from urllib.parse import urljoin

from packages.brain_core.boot import BootContext
from packages.brain_shared.envelope import Envelope, EnvelopeKind, new_meta
from packages.brain_shared.errors import codes, dependency_error, internal_error
from services.action.switchboard.component import SERVICE_COMPONENT_ID
from services.action.switchboard.config import (
    SwitchboardServiceSettings,
    resolve_switchboard_service_settings,
)
from services.action.switchboard.domain import RegisterSignalWebhookResult
from services.action.switchboard.http_ingress import SwitchboardWebhookHttpServer
from services.action.switchboard.service import SwitchboardService

dependencies: tuple[str, ...] = ("adapter_signal", "service_cache_authority")
_WEBHOOK_SERVER: SwitchboardWebhookHttpServer | None = None


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
    """Return true once Switchboard dependencies report ready."""
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
    return payload.service_ready and payload.adapter_ready and payload.cas_ready


def boot(ctx: BootContext) -> None:
    """Execute callback registration during boot once readiness is satisfied."""
    service, settings = _resolve_service_and_settings(ctx)
    _ensure_webhook_ingress_started(service=service, settings=settings)
    run_switchboard_boot_hook(
        service=service,
        settings=settings,
    )


def _ensure_webhook_ingress_started(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
) -> None:
    """Start Switchboard webhook HTTP ingress server once per process."""
    global _WEBHOOK_SERVER
    if _WEBHOOK_SERVER is not None:
        return
    _WEBHOOK_SERVER = SwitchboardWebhookHttpServer(service=service, settings=settings)
    _WEBHOOK_SERVER.start()


def build_switchboard_callback_url(*, settings: SwitchboardServiceSettings) -> str:
    """Build canonical public callback URL from base URL + webhook path."""
    base_url = f"{str(settings.webhook_public_base_url).rstrip('/')}/"
    path = settings.webhook_path.lstrip("/")
    return urljoin(base_url, path)


def register_switchboard_callback_on_boot(
    *,
    service: SwitchboardService,
    settings: SwitchboardServiceSettings,
    source: str = "switchboard_boot",
) -> Envelope[RegisterSignalWebhookResult]:
    """Register webhook callback URI once dependencies are healthy."""
    callback_url = build_switchboard_callback_url(settings=settings)
    attempts = settings.webhook_register_max_retries + 1

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
            and health.payload.value.adapter_ready
            and health.payload.value.cas_ready
        )
        if ready:
            registration_meta = new_meta(
                kind=EnvelopeKind.COMMAND,
                source=source,
                principal="switchboard",
            )
            return service.register_signal_webhook(
                meta=registration_meta,
                callback_url=callback_url,
            )
        if attempt < settings.webhook_register_max_retries:
            sleep(settings.webhook_register_retry_delay_seconds)

    return Envelope[RegisterSignalWebhookResult](
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
