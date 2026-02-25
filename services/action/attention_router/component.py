"""Component declaration for Attention Router Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_attention_router")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.attention_router")}),
        public_api_roots=frozenset(
            {
                ModuleRoot("services.action.attention_router.service"),
                ModuleRoot("services.action.attention_router.domain"),
            }
        ),
        owns_resources=frozenset(),
    )
)
