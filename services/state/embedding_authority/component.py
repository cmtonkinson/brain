"""Component declaration for Embedding Authority Service."""

from __future__ import annotations

from collections.abc import Mapping

from packages.brain_shared.config import BrainSettings
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
        public_api_roots=frozenset(
            {
                # Authoritative L1 public API contract (no transport adapter surface).
                ModuleRoot("services.state.embedding_authority.service")
            }
        ),
        # EAS owns Qdrant substrate; Postgres is shared infrastructure.
        owns_resources=frozenset({ComponentId("substrate_qdrant")}),
    )
)


def build_component(
    *, settings: BrainSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.embedding_authority.service import (
        build_embedding_authority_service,
    )

    return build_embedding_authority_service(
        settings=settings,
        qdrant_substrate=components.get("substrate_qdrant"),
    )
