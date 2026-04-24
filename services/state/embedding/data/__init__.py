"""Embedding-owned Postgres data composition exports."""

from services.state.embedding.data.repository import (
    PostgresEmbeddingRepository,
)
from services.state.embedding.data.runtime import (
    EmbeddingPostgresRuntime,
    embedding_postgres_schema,
)

__all__ = [
    "embedding_postgres_schema",
    "EmbeddingPostgresRuntime",
    "PostgresEmbeddingRepository",
]
