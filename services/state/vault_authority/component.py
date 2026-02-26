"""Component declaration for Vault Authority Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
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


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.vault_authority.service import build_vault_authority_service

    return build_vault_authority_service(
        settings=settings,
        adapter=components.get("adapter_obsidian"),
    )
