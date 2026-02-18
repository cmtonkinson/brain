"""EAS-owned Postgres runtime wiring.

This module composes shared Postgres substrate primitives into a service-local
runtime that enforces EAS schema scoping via ``search_path``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resources.substrates.postgres import (
    PostgresConfig,
    ServiceSchemaSessionProvider,
    create_postgres_engine,
    create_session_factory,
    ping,
)

EMBEDDING_POSTGRES_SCHEMA_DEFAULT = "state_embedding_authority"


@dataclass(frozen=True)
class EmbeddingPostgresRuntime:
    """Concrete EAS-owned handle for schema-scoped Postgres access."""

    engine: Engine
    session_factory: sessionmaker[Session]
    schema_sessions: ServiceSchemaSessionProvider

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "EmbeddingPostgresRuntime":
        """Build EAS DB runtime from merged application configuration."""
        postgres_config = PostgresConfig.from_config(config)
        engine = create_postgres_engine(postgres_config)
        session_factory = create_session_factory(engine)
        schema = embedding_postgres_schema_from_config(config)
        return cls(
            engine=engine,
            session_factory=session_factory,
            schema_sessions=ServiceSchemaSessionProvider(
                session_factory=session_factory,
                schema=schema,
            ),
        )

    def is_healthy(self) -> bool:
        """Return ``True`` when the backing Postgres connection is reachable."""
        return ping(self.engine)


def embedding_postgres_schema_from_config(config: Mapping[str, Any]) -> str:
    """Resolve the owned EAS schema name from merged config with fallback."""
    embedding = config.get("embedding", {}) if isinstance(config, Mapping) else {}
    schema = str(embedding.get("postgres_schema", EMBEDDING_POSTGRES_SCHEMA_DEFAULT)).strip()
    if not schema:
        raise ValueError("embedding.postgres_schema is required")
    if not schema.replace("_", "").isalnum():
        raise ValueError("embedding.postgres_schema must be alphanumeric/underscore")
    return schema
