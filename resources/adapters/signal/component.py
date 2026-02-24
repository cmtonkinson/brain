"""Component declaration for Signal webhook adapter resource."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_signal")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="action",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.signal")}),
        owner_service_id=ComponentId("service_switchboard"),
    )
)
