"""Component declaration for Postgres shared substrate."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_postgres")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.postgres")}),
        owner_service_id=None,
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.postgres.config import resolve_postgres_settings
    from resources.substrates.postgres.substrate import SharedPostgresSubstrate

    return SharedPostgresSubstrate(settings=resolve_postgres_settings(settings))
