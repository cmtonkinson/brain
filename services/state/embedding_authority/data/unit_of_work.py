"""Transactional unit-of-work wrappers for EAS-owned DB operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from resources.substrates.postgres.schema_session import ServiceSchemaSessionProvider
from sqlalchemy.orm import Session

T = TypeVar("T")


class EmbeddingDataUnitOfWork:
    """Execute EAS persistence work inside one schema-scoped transaction."""

    def __init__(self, sessions: ServiceSchemaSessionProvider) -> None:
        self._sessions = sessions

    def run(self, fn: Callable[[Session], T]) -> T:
        """Run one callback in a schema-scoped transaction with session access."""
        with self._sessions.session() as session:
            return fn(session)
