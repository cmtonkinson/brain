"""Component declaration for Job Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_job")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="control",
        module_roots=frozenset({ModuleRoot("services.control.job")}),
        public_api_roots=frozenset({ModuleRoot("services.control.job.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.capability_engine.service import CapabilityEngineService
    from services.control.job.service import build_job_service

    capability_engine_service = components.get("service_capability_engine")
    if not isinstance(capability_engine_service, CapabilityEngineService):
        raise KeyError("service_capability_engine")

    return build_job_service(
        settings=settings,
        capability_engine_service=capability_engine_service,
    )
