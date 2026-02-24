"""Component declaration for Vault Authority Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_vault_authority")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.vault_authority")}),
        public_api_roots=frozenset(
            {ModuleRoot("services.state.vault_authority.service")}
        ),
        owns_resources=frozenset({ComponentId("adapter_obsidian")}),
    )
)
