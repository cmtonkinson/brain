"""Component declaration for Object Authority Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_object_authority")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.object_authority")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.state.object_authority.service")}
        ),
        owns_resources=frozenset({ComponentId("substrate_filesystem")}),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.object_authority.service import build_object_authority_service

    return build_object_authority_service(
        settings=settings,
        blob_store=components.get("substrate_filesystem"),
    )
