"""Component declaration for Utility Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_utility_service")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.utility_service")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.action.utility_service.service"),
                ModuleRoot("services.action.utility_service.domain"),
            }
        ),
        owns_resources=frozenset(),
        exposes_capabilities=True,
        tool_system_label="Utility Service",
        tool_system_summary="Lightweight reusable helper operations.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.action.utility_service.service import build_utility_service

    del components
    return build_utility_service(settings=settings)
