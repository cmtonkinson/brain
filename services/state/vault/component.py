"""Component declaration for Vault Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_vault")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="state",
        module_roots=frozenset({ModuleRoot("services.state.vault")}),
        public_api_roots=frozenset({ModuleRoot("services.state.vault.service")}),
        owns_resources=frozenset({ComponentId("substrate_obsidian")}),
        exposes_ops=True,
        tool_system_label="Vault Service",
        tool_system_summary="Personal Knowledge Base access through the Obsidian vault.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.vault.service import build_vault_service

    return build_vault_service(
        settings=settings,
        substrate=components.get("substrate_obsidian"),
    )
