"""Component declaration for Obsidian Local REST API substrate resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_obsidian")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.obsidian")}),
        owner_service_id=ComponentId("service_vault_authority"),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.obsidian.config import resolve_obsidian_substrate_settings
    from resources.substrates.obsidian.obsidian_substrate import (
        ObsidianLocalRestSubstrate,
    )

    return ObsidianLocalRestSubstrate(
        settings=resolve_obsidian_substrate_settings(settings),
    )
