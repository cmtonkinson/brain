"""Component declaration for Object Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_object")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="state",
        module_roots=frozenset({ModuleRoot("services.state.object")}),
        public_api_roots=frozenset({ModuleRoot("services.state.object.service")}),
        owns_resources=frozenset({ComponentId("substrate_seaweedfs")}),
        exposes_ops=True,
        tool_system_label="Object Service",
        tool_system_summary="Durable content-addressed blob storage.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.object.service import build_object_service

    return build_object_service(
        settings=settings,
        blob_store=components.get("substrate_seaweedfs"),
    )
