"""Shared Postgres substrate contract and implementation."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Engine

from resources.substrates.postgres.config import PostgresSettings
from resources.substrates.postgres.engine import create_postgres_engine
from resources.substrates.postgres.health import ping


class PostgresHealthStatus(BaseModel):
    """Postgres substrate readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class PostgresSubstrate(Protocol):
    """Protocol for shared Postgres substrate operations."""

    @property
    def engine(self) -> Engine:
        """Return underlying SQLAlchemy engine."""

    def health(self) -> PostgresHealthStatus:
        """Probe Postgres substrate readiness."""


class SharedPostgresSubstrate(PostgresSubstrate):
    """Concrete shared Postgres substrate with readiness probe."""

    def __init__(self, *, settings: PostgresSettings) -> None:
        self._settings = settings
        self._engine = create_postgres_engine(settings)

    @property
    def engine(self) -> Engine:
        """Return underlying SQLAlchemy engine."""
        return self._engine

    def health(self) -> PostgresHealthStatus:
        """Return readiness from a bounded Postgres ping."""
        try:
            ready = ping(
                self._engine,
                timeout_seconds=self._settings.health_timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            return PostgresHealthStatus(
                ready=False,
                detail=f"postgres health probe failed: {type(exc).__name__}",
            )
        return PostgresHealthStatus(
            ready=ready,
            detail="ok" if ready else "postgres ping failed",
        )
