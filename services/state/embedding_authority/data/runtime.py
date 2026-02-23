"""EAS-owned Postgres runtime wiring.

This module composes shared Postgres substrate primitives into a service-local
runtime that enforces EAS schema scoping via ``search_path``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from packages.brain_shared.config import BrainSettings
from packages.brain_shared.manifest import component_id_to_schema_name
from resources.substrates.postgres import (
    ServiceSchemaSessionProvider,
    create_postgres_engine,
    create_session_factory,
    ping,
)
from resources.substrates.postgres.config import resolve_postgres_settings
from services.state.embedding_authority.component import SERVICE_COMPONENT_ID


@dataclass(frozen=True)
class EmbeddingPostgresRuntime:
    """Concrete EAS-owned handle for schema-scoped Postgres access."""

    engine: Engine
    session_factory: sessionmaker[Session]
    schema_sessions: ServiceSchemaSessionProvider

    @classmethod
    def from_settings(cls, settings: BrainSettings) -> "EmbeddingPostgresRuntime":
        """Build EAS DB runtime from typed application settings."""
        postgres_config = resolve_postgres_settings(settings)
        engine = create_postgres_engine(postgres_config)
        session_factory = create_session_factory(engine)
        schema = embedding_postgres_schema()
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


def embedding_postgres_schema() -> str:
    """Resolve the canonical EAS schema name from component identity."""
    return component_id_to_schema_name(SERVICE_COMPONENT_ID)
