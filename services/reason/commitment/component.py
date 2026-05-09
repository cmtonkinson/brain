"""Component declaration for Commitment Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_commitment")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="reason",
        module_roots=frozenset({ModuleRoot("services.reason.commitment")}),
        public_api_roots=frozenset({ModuleRoot("services.reason.commitment.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.reason.commitment.service import build_commitment_service

    return build_commitment_service(settings=settings, components=components)


def after_boot(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> None:
    """Register the periodic turn-scanner interval job if enabled."""
    from lib.shared.envelope import EnvelopeKind, new_meta
    from services.reason.commitment.config import resolve_commitment_service_settings
    from services.reason.job.service import JobService

    svc_settings = resolve_commitment_service_settings(settings)
    if not svc_settings.turn_scanner_enabled:
        return

    job_service = components.get("service_job")
    if not isinstance(job_service, JobService):
        return

    origin_ref = "commitment:turn-scanner:interval"
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source=str(SERVICE_COMPONENT_ID),
        principal="system",
    )

    existing = job_service.find_job_by_origin_reference(
        meta=meta, origin_reference=origin_ref
    )
    if existing.ok and existing.payload.value is not None:
        record = existing.payload.value
        if record.state not in ("canceled", "completed", "archived"):
            return

    job_service.create_job(
        meta=meta,
        summary="Periodic commitment turn scanner",
        details="Scans recent inbound Recall turns for commitment candidates.",
        origin_reference=origin_ref,
        schedule_type="interval",
        timezone=svc_settings.default_timezone,
        definition={
            "interval_count": svc_settings.turn_scanner_interval_minutes,
            "interval_unit": "minute",
        },
        job_action={
            "type": "op_invocation",
            "op_id": svc_settings.turn_scanner_op_id,
            "input_payload": {},
        },
        start_state="active",
    )
