"""Component declaration for Capability Engine Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_capability_engine")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.capability_engine")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.action.capability_engine.service")}
        ),
        owns_resources=frozenset({ComponentId("adapter_utcp_code_mode")}),
    )
)
