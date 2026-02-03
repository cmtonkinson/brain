"""Repository helpers for commitment schedule linking records."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from models import Commitment, CommitmentScheduleLink
from time_utils import to_utc


@dataclass(frozen=True)
class CommitmentScheduleLinkCreateInput:
    """Input payload for creating a commitment schedule link."""

    commitment_id: int
    schedule_id: int
    created_at: datetime | None = None
    is_active: bool = True


class CommitmentScheduleLinkRepository:
    """Repository for commitment schedule link persistence."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create(self, payload: CommitmentScheduleLinkCreateInput) -> CommitmentScheduleLink:
        """Create and persist a commitment schedule link."""

        def handler(session: Session) -> CommitmentScheduleLink:
            return create_link_record(session, payload)

        return self._execute(handler)

    def deactivate(self, commitment_id: int, schedule_id: int) -> CommitmentScheduleLink:
        """Deactivate an existing commitment schedule link."""

        def handler(session: Session) -> CommitmentScheduleLink:
            return deactivate_link_record(session, commitment_id, schedule_id)

        return self._execute(handler)

    def resolve_commitment_by_schedule_id(self, schedule_id: int) -> Commitment | None:
        """Return the linked commitment for an active schedule link."""

        def handler(session: Session) -> Commitment | None:
            return (
                session.query(Commitment)
                .join(
                    CommitmentScheduleLink,
                    CommitmentScheduleLink.commitment_id == Commitment.commitment_id,
                )
                .filter(
                    CommitmentScheduleLink.schedule_id == schedule_id,
                    CommitmentScheduleLink.is_active.is_(True),
                )
                .one_or_none()
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


def create_link_record(
    session: Session,
    payload: CommitmentScheduleLinkCreateInput,
) -> CommitmentScheduleLink:
    """Create a commitment schedule link using an existing session."""
    link = CommitmentScheduleLink(
        commitment_id=payload.commitment_id,
        schedule_id=payload.schedule_id,
        created_at=_normalize_timestamp(payload.created_at or datetime.now(timezone.utc)),
        is_active=payload.is_active,
    )
    session.add(link)
    session.flush()
    return link


def deactivate_link_record(
    session: Session,
    commitment_id: int,
    schedule_id: int,
) -> CommitmentScheduleLink:
    """Deactivate a commitment schedule link using an existing session."""
    link = (
        session.query(CommitmentScheduleLink)
        .filter(
            CommitmentScheduleLink.commitment_id == commitment_id,
            CommitmentScheduleLink.schedule_id == schedule_id,
        )
        .one_or_none()
    )
    if link is None:
        raise ValueError(f"Commitment schedule link not found: {commitment_id} -> {schedule_id}")
    link.is_active = False
    session.flush()
    return link
