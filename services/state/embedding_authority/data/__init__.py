"""EAS Postgres data-access composition primitives.

This package contains only EAS-owned DB access wiring. It does not expose any
cross-service schema access and is intentionally transport-agnostic.
"""

from services.state.embedding_authority.data.runtime import (
    EmbeddingPostgresRuntime,
    embedding_postgres_schema,
)
from services.state.embedding_authority.data.repository import EmbeddingAuditRepository
from services.state.embedding_authority.data.types import EmbeddingAuditEntry
from services.state.embedding_authority.data.unit_of_work import EmbeddingDataUnitOfWork

__all__ = [
    "embedding_postgres_schema",
    "EmbeddingPostgresRuntime",
    "EmbeddingAuditRepository",
    "EmbeddingAuditEntry",
    "EmbeddingDataUnitOfWork",
]
