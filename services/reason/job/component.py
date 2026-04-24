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
        tier=2,
        plane="reason",
        module_roots=frozenset({ModuleRoot("services.reason.job")}),
        public_api_roots=frozenset({ModuleRoot("services.reason.job.service")}),
        owns_resources=frozenset(),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.execution.service import ExecutionService
    from services.reason.job.service import build_job_service

    execution_service = components.get("service_execution")
    if not isinstance(execution_service, ExecutionService):
        raise KeyError("service_execution")

    return build_job_service(
        settings=settings,
        execution_service=execution_service,
    )
