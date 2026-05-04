"""Component declaration for Software Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_software")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="effect",
        module_roots=frozenset({ModuleRoot("services.effect.software")}),
        public_api_roots=frozenset({ModuleRoot("services.effect.software.service")}),
        owns_resources=frozenset({ComponentId("adapter_coding")}),
        exposes_ops=True,
        tool_system_label="Software Service",
        tool_system_summary=(
            "Coding tasks against operator-allowlisted repos, executed in "
            "ephemeral containers via the Coding Adapter."
        ),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.effect.software.service import build_software_service

    return build_software_service(
        settings=settings,
        adapter=components.get("adapter_coding"),
        object_service=components.get("service_object"),
    )
