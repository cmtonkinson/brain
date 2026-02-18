"""Embedding Authority Service native package exports.

This module intentionally exports only the native, in-process EAS API surface.
The gRPC adapter layer is available from `services.state.embedding_authority.api`
and is kept out of default imports to preserve transport optionality for
east-west callers.
"""

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from packages.brain_shared.manifest import (
    ComponentId,
    ModuleRoot,
    register_component,
    ServiceManifest,
)
from services.state.embedding_authority.domain import (
    EmbeddingMatch,
    EmbeddingRecord,
    EmbeddingRef,
)
from services.state.embedding_authority.implementation import (
    DefaultEmbeddingAuthorityService,
)
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.embedding_authority.settings import EmbeddingSettings

MANIFEST = register_component(
    ServiceManifest(
        id=ComponentId("service_embedding_authority"),
        layer=1,
        system="state",
        module_roots=frozenset({ModuleRoot("services.state.embedding_authority")}),
        public_api_roots=frozenset({ModuleRoot("services.state.embedding_authority")}),
        # EAS owns Qdrant substrate; Postgres is shared infrastructure.
        owns_resources=frozenset({ComponentId("substrate_qdrant")}),
    )
)

__all__ = [
    "EmbeddingAuthorityService",
    "EmbeddingMatch",
    "EmbeddingRecord",
    "EmbeddingRef",
    "EmbeddingSettings",
    "DefaultEmbeddingAuthorityService",
    "EnvelopeKind",
    "EnvelopeMeta",
    "ErrorCategory",
    "ErrorDetail",
    "Result",
    "MANIFEST",
]
