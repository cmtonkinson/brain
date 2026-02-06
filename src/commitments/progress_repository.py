"""Repository helpers for commitment progress records."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from models import CommitmentProgress
from time_utils import to_utc


@dataclass(frozen=True)
class CommitmentProgressCreateInput:
    """Input payload for creating a commitment progress record."""

    commitment_id: int
    provenance_id: UUID | None
    occurred_at: datetime
    summary: str
    snippet: str | None = None
    metadata: dict | list | str | int | float | bool | None = None


class CommitmentProgressRepository:
    """Repository for commitment progress persistence and queries."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create(self, payload: CommitmentProgressCreateInput) -> CommitmentProgress:
        """Create and persist a commitment progress record."""

        def handler(session: Session) -> CommitmentProgress:
            return create_progress_record(session, payload)

        return self._execute(handler)

    def list_by_commitment_id(self, commitment_id: int) -> list[CommitmentProgress]:
        """Return progress records ordered by occurred_at descending."""

        def handler(session: Session) -> list[CommitmentProgress]:
            return (
                session.query(CommitmentProgress)
                .filter(CommitmentProgress.commitment_id == commitment_id)
                .order_by(CommitmentProgress.occurred_at.desc())
                .all()
            )

        return self._execute(handler)

    def _execute(self, handler):
        """Execute repository work inside a managed session."""
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                result = handler(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
        return result


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize a datetime value to UTC."""
    return to_utc(value)


def create_progress_record(
    session: Session,
    payload: CommitmentProgressCreateInput,
) -> CommitmentProgress:
    """Create a commitment progress record using an existing session."""
    record = CommitmentProgress(
        commitment_id=payload.commitment_id,
        provenance_id=payload.provenance_id,
        occurred_at=_normalize_timestamp(payload.occurred_at),
        summary=payload.summary,
        snippet=payload.snippet,
        metadata_=payload.metadata,
    )
    session.add(record)
    session.flush()
    return record
