"""Component declaration for Memory Authority Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_memory_authority")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.memory_authority")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.state.memory_authority.service")}
        ),
        # MAS uses shared Postgres infrastructure; no dedicated L0 resource component.
        owns_resources=frozenset(),
    )
)
