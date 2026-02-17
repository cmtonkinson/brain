"""Service for managing commitment schedule links and next_schedule_id updates."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from commitments.repository import CommitmentUpdateInput, _apply_updates, _fetch_commitment
from commitments.schedule_links import (
    CommitmentScheduleLinkCreateInput,
    create_link_record,
    deactivate_link_record,
)
from models import CommitmentScheduleLink
from time_utils import to_utc


class CommitmentScheduleLinkService:
    """Service enforcing one-active-link constraints for commitments."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the service with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create_link(
        self,
        *,
        commitment_id: int,
        schedule_id: int,
        now: datetime | None = None,
    ) -> CommitmentScheduleLink:
        """Create a new active link, deactivating any existing active links."""
        timestamp = to_utc(now or datetime.now(timezone.utc))
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                commitment = _fetch_commitment(session, commitment_id)
                active_links = (
                    session.query(CommitmentScheduleLink)
                    .filter(
                        CommitmentScheduleLink.commitment_id == commitment_id,
                        CommitmentScheduleLink.is_active.is_(True),
                    )
                    .all()
                )
                for link in active_links:
                    link.is_active = False

                created = create_link_record(
                    session,
                    CommitmentScheduleLinkCreateInput(
                        commitment_id=commitment_id,
                        schedule_id=schedule_id,
                        created_at=timestamp,
                        is_active=True,
                    ),
                )
                _apply_updates(
                    commitment,
                    CommitmentUpdateInput(next_schedule_id=schedule_id),
                )
                commitment.updated_at = timestamp
                session.commit()
            except Exception:
                session.rollback()
                raise

        return created

    def deactivate_link(
        self,
        *,
        commitment_id: int,
        schedule_id: int,
        now: datetime | None = None,
    ) -> CommitmentScheduleLink:
        """Deactivate a link and clear the commitment's next_schedule_id."""
        timestamp = to_utc(now or datetime.now(timezone.utc))
        with closing(self._session_factory()) as session:
            session.expire_on_commit = False
            try:
                commitment = _fetch_commitment(session, commitment_id)
                link = deactivate_link_record(session, commitment_id, schedule_id)
                _apply_updates(commitment, CommitmentUpdateInput(next_schedule_id=None))
                commitment.updated_at = timestamp
                session.commit()
            except Exception:
                session.rollback()
                raise

        return link

    def get_active_schedule_id(self, commitment_id: int) -> int | None:
        """Return the active schedule_id for a commitment, if any."""
        with closing(self._session_factory()) as session:
            return self._get_active_schedule_id_in_session(session, commitment_id)

    def get_active_schedule_id_in_session(
        self,
        session: Session,
        commitment_id: int,
    ) -> int | None:
        """Return the active schedule_id for a commitment using an existing session."""
        return self._get_active_schedule_id_in_session(session, commitment_id)

    @staticmethod
    def _get_active_schedule_id_in_session(
        session: Session,
        commitment_id: int,
    ) -> int | None:
        """Query the active schedule_id for a commitment within a session."""
        link = (
            session.query(CommitmentScheduleLink)
            .filter(
                CommitmentScheduleLink.commitment_id == commitment_id,
                CommitmentScheduleLink.is_active.is_(True),
            )
            .order_by(CommitmentScheduleLink.created_at.desc())
            .first()
        )
        return link.schedule_id if link is not None else None
