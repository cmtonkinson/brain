"""Component declaration for Valkey substrate resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_valkey")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.valkey")}),
        owner_service_id=ComponentId("service_cache_authority"),
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.valkey.config import resolve_valkey_settings
    from resources.substrates.valkey.valkey_substrate import ValkeyClientSubstrate

    return ValkeyClientSubstrate(settings=resolve_valkey_settings(settings))
