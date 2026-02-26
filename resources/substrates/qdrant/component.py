"""Component declaration for Qdrant substrate resource."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)

RESOURCE_COMPONENT_ID = ComponentId("substrate_qdrant")

MANIFEST = register_component(
    ResourceManifest(
        id=RESOURCE_COMPONENT_ID,
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.qdrant")}),
        owner_service_id=ComponentId("service_embedding_authority"),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered resource component."""
    del components
    from resources.substrates.qdrant.config import QdrantConfig, QdrantSettings
    from resources.substrates.qdrant.qdrant_substrate import QdrantClientSubstrate

    substrate_settings = resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=QdrantSettings,
    )
    return QdrantClientSubstrate(
        QdrantConfig(
            url=substrate_settings.url,
            timeout_seconds=substrate_settings.request_timeout_seconds,
            collection_name="brain_runtime",
            distance_metric=substrate_settings.distance_metric,
        )
    )
