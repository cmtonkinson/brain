"""Service-schema scoped session helpers for Postgres shared infrastructure."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from resources.substrates.postgres.session import transactional_session


class ServiceSchemaSessionProvider:
    """Provide transactional sessions pinned to one service-owned schema."""

    def __init__(self, *, session_factory: sessionmaker[Session], schema: str) -> None:
        self._session_factory = session_factory
        self._schema = schema
        self._validate_schema(schema)

    @property
    def schema(self) -> str:
        """Return the owned schema name for this provider."""
        return self._schema

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a transaction-scoped session with local search_path set."""
        with transactional_session(self._session_factory) as db:
            db.execute(text(f"SET LOCAL search_path TO {self._schema}, public"))
            yield db

    def _validate_schema(self, schema: str) -> None:
        """Validate schema names to prevent malformed search_path statements."""
        if not schema:
            raise ValueError("postgres schema is required")
        if not schema.replace("_", "").isalnum():
            raise ValueError("postgres schema must be alphanumeric/underscore")
