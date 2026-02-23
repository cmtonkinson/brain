"""Component declaration for Obsidian Local REST API adapter resource."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("adapter_obsidian")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="adapter",
        module_roots=frozenset({ModuleRoot("resources.adapters.obsidian")}),
        owner_service_id=ComponentId("service_vault_authority"),
    )
)
