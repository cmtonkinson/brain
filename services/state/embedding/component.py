"""Component declaration for Embedding Service."""

from __future__ import annotations

from collections.abc import Mapping

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import (
    ComponentId,
    ModuleRoot,
    ServiceManifest,
    register_component,
)

SERVICE_COMPONENT_ID = ComponentId("service_embedding")

MANIFEST = register_component(
    ServiceManifest(
        id=SERVICE_COMPONENT_ID,
        tier=2,
        plane="state",
        module_roots=frozenset({ModuleRoot("services.state.embedding")}),
        public_api_roots=frozenset(
            {
                # Authoritative Tier 2 public API contract (no transport adapter surface).
                ModuleRoot("services.state.embedding.service")
            }
        ),
        # Embedding owns Qdrant substrate; Postgres is shared infrastructure.
        owns_resources=frozenset({ComponentId("substrate_qdrant")}),
        exposes_ops=True,
        tool_system_label="Embedding Service",
        tool_system_summary="Semantic vector indexing and search over derived text chunks.",
    )
)


def build_component(
    *, settings: CoreRuntimeSettings, components: Mapping[str, object]
) -> object:
    """Build concrete runtime instance for this registered service component."""
    from services.state.embedding.service import (
        build_embedding_service,
    )

    return build_embedding_service(
        settings=settings,
        qdrant_substrate=components.get("substrate_qdrant"),
    )
