"""Component declaration for Switchboard Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_switchboard")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="action",
        module_roots=frozenset({ModuleRoot("services.action.switchboard")}),
        public_api_roots=frozenset({ModuleRoot("services.action.switchboard.service")}),
        owns_resources=frozenset({ComponentId("adapter_signal")}),
    )
)
