"""Service for atomic commitment progress recording."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from commitments.progress_repository import (
    CommitmentProgressCreateInput,
    create_progress_record,
)
from commitments.repository import _fetch_commitment
from models import CommitmentProgress
from time_utils import to_utc


class CommitmentProgressService:
    """Service to record progress and update last_progress_at atomically."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the service with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def record_progress(
        self,
        *,
        commitment_id: int,
        provenance_id: UUID,
        occurred_at: datetime,
        summary: str,
        snippet: str | None = None,
        metadata: dict | list | str | int | float | bool | None = None,
    ) -> CommitmentProgress:
        """Record progress and update last_progress_at in a single transaction."""
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                commitment = _fetch_commitment(session, commitment_id)
                record = create_progress_record(
                    session,
                    CommitmentProgressCreateInput(
                        commitment_id=commitment_id,
                        provenance_id=provenance_id,
                        occurred_at=occurred_at,
                        summary=summary,
                        snippet=snippet,
                        metadata=metadata,
                    ),
                )
                commitment.last_progress_at = to_utc(occurred_at)
                session.commit()
            except Exception:
                session.rollback()
                raise

        return record
