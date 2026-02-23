"""Component declaration for Object Authority Service."""

from __future__ import annotations

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
        owns_resources=frozenset({ComponentId("adapter_filesystem")}),
    )
)
