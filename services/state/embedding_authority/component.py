"""Component declaration for Embedding Authority Service."""

from __future__ import annotations

from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_embedding_authority")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.embedding_authority")}),
        public_api_roots=frozenset({ModuleRoot("services.state.embedding_authority")}),
        # EAS owns Qdrant substrate; Postgres is shared infrastructure.
        owns_resources=frozenset({ComponentId("substrate_qdrant")}),
    )
)
