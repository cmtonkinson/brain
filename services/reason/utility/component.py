"""Component declaration for Utility Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_utility")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="reason",
        module_roots=frozenset({ModuleRoot("services.reason.utility")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.reason.utility.service"),
                ModuleRoot("services.reason.utility.domain"),
            }
        ),
        owns_resources=frozenset(),
        exposes_ops=True,
        tool_system_label="Utility Service",
        tool_system_summary="Lightweight reusable helper operations.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.reason.utility.service import build_utility_service

    del components
    return build_utility_service(settings=settings)
