"""SQLAlchemy engine construction for shared Postgres substrate."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine

from packages.brain_shared.config import PostgresSettings


def create_postgres_engine(config: PostgresSettings) -> Engine:
    """Construct a configured SQLAlchemy engine using psycopg."""
    config.validate()
    connect_args = {
        "connect_timeout": int(config.connect_timeout_seconds),
        "sslmode": config.sslmode,
    }
    return create_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout_seconds,
        pool_pre_ping=config.pool_pre_ping,
        connect_args=connect_args,
    )
