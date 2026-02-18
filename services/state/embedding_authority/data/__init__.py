"""EAS Postgres data-access composition primitives.

This package contains only EAS-owned DB access wiring. It does not expose any
cross-service schema access and is intentionally transport-agnostic.
"""

from services.state.embedding_authority.data.runtime import (
    EMBEDDING_POSTGRES_SCHEMA_DEFAULT,
    EmbeddingPostgresRuntime,
    embedding_postgres_schema_from_config,
)
from services.state.embedding_authority.data.repository import EmbeddingAuditRepository
from services.state.embedding_authority.data.types import EmbeddingAuditEntry
from services.state.embedding_authority.data.unit_of_work import EmbeddingDataUnitOfWork

__all__ = [
    "EMBEDDING_POSTGRES_SCHEMA_DEFAULT",
    "embedding_postgres_schema_from_config",
    "EmbeddingPostgresRuntime",
    "EmbeddingAuditRepository",
    "EmbeddingAuditEntry",
    "EmbeddingDataUnitOfWork",
]
