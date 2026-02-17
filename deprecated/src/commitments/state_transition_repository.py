"""Repository helpers for commitment state transition persistence."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from models import CommitmentStateTransition
from time_utils import to_utc


@dataclass(frozen=True)
class CommitmentStateTransitionCreateInput:
    """Input payload for creating a commitment state transition audit record."""

    commitment_id: int
    from_state: str
    to_state: str
    actor: str
    reason: str | None = None
    context: Mapping[str, object] | None = None
    confidence: float | None = None
    provenance_id: UUID | None = None
    transitioned_at: datetime | None = None


class CommitmentStateTransitionRepository:
    """Repository for commitment state transition audit records."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create(
        self,
        payload: CommitmentStateTransitionCreateInput,
        *,
        now: datetime | None = None,
    ) -> CommitmentStateTransition:
        """Create and persist a commitment state transition audit record."""

        def handler(session: Session) -> CommitmentStateTransition:
            return create_transition_record(session, payload, now=now)

        return self._execute(handler)

    def list_for_commitment(
        self,
        commitment_id: int,
        *,
        limit: int | None = None,
    ) -> list[CommitmentStateTransition]:
        """Return transition history for a commitment ordered by transitioned_at desc."""

        def handler(session: Session) -> list[CommitmentStateTransition]:
            query = (
                session.query(CommitmentStateTransition)
                .filter(CommitmentStateTransition.commitment_id == commitment_id)
                .order_by(
                    CommitmentStateTransition.transitioned_at.desc(),
                    CommitmentStateTransition.transition_id.desc(),
                )
            )
            if limit is not None:
                query = query.limit(limit)
            return list(query.all())

        return self._execute(handler)

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete transition records older than the cutoff timestamp."""

        def handler(session: Session) -> int:
            return delete_transitions_older_than(session, cutoff)

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


def build_retention_cleanup_query(days: int):
    """Build a retention cleanup SQL template for transitions older than N days."""
    if days <= 0:
        raise ValueError("Retention cleanup days must be greater than zero.")
    return text(
        "DELETE FROM commitment_state_transitions "
        "WHERE transitioned_at < NOW() - (:days * INTERVAL '1 day')",
    )


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize a datetime value to UTC."""
    return to_utc(value)


def delete_transitions_older_than(session: Session, cutoff: datetime) -> int:
    """Delete transition records older than the cutoff timestamp."""
    normalized_cutoff = _normalize_timestamp(cutoff)
    deleted = (
        session.query(CommitmentStateTransition)
        .filter(CommitmentStateTransition.transitioned_at < normalized_cutoff)
        .delete(synchronize_session=False)
    )
    session.flush()
    return int(deleted or 0)


def create_transition_record(
    session: Session,
    payload: CommitmentStateTransitionCreateInput,
    *,
    now: datetime | None = None,
) -> CommitmentStateTransition:
    """Create a commitment state transition using an existing session."""
    transitioned_at = _normalize_timestamp(
        payload.transitioned_at or now or datetime.now(timezone.utc)
    )
    transition = CommitmentStateTransition(
        commitment_id=payload.commitment_id,
        from_state=payload.from_state,
        to_state=payload.to_state,
        transitioned_at=transitioned_at,
        actor=payload.actor,
        reason=payload.reason,
        context=dict(payload.context) if payload.context is not None else None,
        confidence=payload.confidence,
        provenance_id=payload.provenance_id,
    )
    session.add(transition)
    session.flush()
    return transition
