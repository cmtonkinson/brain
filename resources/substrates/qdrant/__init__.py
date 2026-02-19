"""Qdrant substrate modules for Layer 0 resource access."""

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ResourceManifest,
    register_component,
)
from resources.substrates.qdrant.config import QdrantConfig
from resources.substrates.qdrant.qdrant_substrate import QdrantClientSubstrate
from resources.substrates.qdrant.substrate import (
    QdrantSubstrate,
    RetrievedPoint,
    SearchPoint,
)

MANIFEST = register_component(
    ResourceManifest(
        id=ComponentId("substrate_qdrant"),
        layer=0,
        system="state",
        kind="substrate",
        module_roots=frozenset({ModuleRoot("resources.substrates.qdrant")}),
        owner_service_id=ComponentId("service_embedding_authority"),
    )
)

__all__ = [
    "QdrantConfig",
    "QdrantSubstrate",
    "RetrievedPoint",
    "SearchPoint",
    "QdrantClientSubstrate",
    "MANIFEST",
]
