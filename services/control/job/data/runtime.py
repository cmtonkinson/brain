"""Job Service-owned Postgres runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from lib.shared.config import CoreRuntimeSettings
from lib.shared.manifest import component_id_to_schema_name
from resources.substrates.postgres import (
    ServiceSchemaSessionProvider,
    create_postgres_engine,
    create_session_factory,
    ping,
)
from resources.substrates.postgres.config import resolve_postgres_settings
from services.control.job.component import SERVICE_COMPONENT_ID


@dataclass(frozen=True)
class JobPostgresRuntime:
    """Concrete Job Service-owned handle for schema-scoped Postgres access."""

    engine: Engine
    session_factory: sessionmaker[Session]
    schema_sessions: ServiceSchemaSessionProvider
    health_timeout_seconds: float

    @classmethod
    def from_settings(cls, settings: CoreRuntimeSettings) -> JobPostgresRuntime:
        """Build Job DB runtime from typed application settings."""
        postgres_config = resolve_postgres_settings(settings)
        engine = create_postgres_engine(postgres_config)
        session_factory = create_session_factory(engine)
        schema = job_postgres_schema()
        return cls(
            engine=engine,
            session_factory=session_factory,
            schema_sessions=ServiceSchemaSessionProvider(
                session_factory=session_factory,
                schema=schema,
            ),
            health_timeout_seconds=postgres_config.health_timeout_seconds,
        )

    def is_healthy(self) -> bool:
        """Return ``True`` when backing Postgres connection is reachable."""
        return ping(self.engine, timeout_seconds=self.health_timeout_seconds)


def job_postgres_schema() -> str:
    """Resolve canonical Job Service schema name from component identity."""
    return component_id_to_schema_name(SERVICE_COMPONENT_ID)
