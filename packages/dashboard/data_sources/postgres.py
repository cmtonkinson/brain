"""Read-only Postgres access for dashboard data sources."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from packages.dashboard.data_sources.base import BasePollingDataSource
from packages.dashboard.models.data_source import RetentionPolicy

T = TypeVar("T")


class PostgresConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    url: str
    pool_size: int = Field(default=3, gt=0)
    query_timeout_seconds: float = Field(default=5.0, gt=0)
    read_only: bool = True


def normalize_postgres_dsn(url: str) -> str:
    """Convert SQLAlchemy-style psycopg URLs into plain libpq DSNs."""
    normalized = url.strip()
    prefix = "postgresql+psycopg://"
    if normalized.startswith(prefix):
        return f"postgresql://{normalized.removeprefix(prefix)}"
    return normalized


class BasePostgresDataSource(BasePollingDataSource[T], Generic[T]):
    def __init__(
        self,
        config: PostgresConnectionConfig,
        poll_interval: float,
        retention: RetentionPolicy,
    ) -> None:
        super().__init__(poll_interval, retention)
        self._config = config
        self._conn = None

    def _get_connection(self):
        import psycopg  # noqa: PLC0415

        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                normalize_postgres_dsn(self._config.url),
                autocommit=True,
                options="-c default_transaction_read_only=on",
                connect_timeout=max(1, int(self._config.query_timeout_seconds)),
            )
        return self._conn

    def _fetch(self) -> T | None:
        conn = self._get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return None  # subclasses override with real queries

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
