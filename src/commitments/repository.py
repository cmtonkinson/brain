"""Repository helpers for commitment persistence."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from commitments.urgency import compute_urgency
from models import Commitment, Schedule
from time_utils import get_local_timezone, to_utc

UNSET = object()
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommitmentCreateInput:
    """Input payload for creating a commitment record."""

    description: str
    provenance_id: UUID | None = None
    state: str = "OPEN"
    importance: int = 2
    effort_provided: int = 2
    effort_inferred: int | None = None
    urgency: int | None = None
    due_by: date | datetime | None = None
    last_progress_at: datetime | None = None
    last_modified_at: datetime | None = None
    ever_missed_at: datetime | None = None
    presented_for_review_at: datetime | None = None
    reviewed_at: datetime | None = None
    next_schedule_id: int | None = None


@dataclass(frozen=True)
class CommitmentUpdateInput:
    """Input payload for updating commitment fields."""

    description: str | object = UNSET
    provenance_id: UUID | None | object = UNSET
    state: str | object = UNSET
    importance: int | object = UNSET
    effort_provided: int | object = UNSET
    effort_inferred: int | None | object = UNSET
    urgency: int | None | object = UNSET
    due_by: date | datetime | None | object = UNSET
    last_progress_at: datetime | None | object = UNSET
    last_modified_at: datetime | None | object = UNSET
    ever_missed_at: datetime | None | object = UNSET
    presented_for_review_at: datetime | None | object = UNSET
    reviewed_at: datetime | None | object = UNSET
    next_schedule_id: int | None | object = UNSET


class CommitmentRepository:
    """Repository for commitment CRUD operations."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize repository with a SQLAlchemy session factory."""
        self._session_factory = session_factory

    def create(
        self,
        payload: CommitmentCreateInput,
        *,
        now: datetime | None = None,
    ) -> Commitment:
        """Create and persist a commitment record."""

        def handler(session: Session) -> Commitment:
            timestamp = _normalize_timestamp(now or datetime.now(timezone.utc))
            due_by = _normalize_due_by(payload.due_by)
            urgency = compute_urgency(
                payload.importance,
                payload.effort_provided,
                due_by,
                timestamp,
            )
            commitment = Commitment(
                description=payload.description,
                provenance_id=payload.provenance_id,
                state=payload.state,
                importance=payload.importance,
                effort_provided=payload.effort_provided,
                effort_inferred=payload.effort_inferred,
                urgency=urgency,
                due_by=due_by,
                created_at=timestamp,
                updated_at=timestamp,
                last_progress_at=_normalize_optional_timestamp(payload.last_progress_at),
                last_modified_at=_normalize_optional_timestamp(payload.last_modified_at),
                ever_missed_at=_normalize_optional_timestamp(payload.ever_missed_at),
                presented_for_review_at=_normalize_optional_timestamp(
                    payload.presented_for_review_at
                ),
                reviewed_at=_normalize_optional_timestamp(payload.reviewed_at),
                next_schedule_id=payload.next_schedule_id,
            )
            session.add(commitment)
            session.flush()
            _maybe_log_urgency_warning(
                commitment.commitment_id,
                urgency,
                session=session,
                now=timestamp,
            )
            return commitment

        return self._execute(handler)

    def get_by_id(self, commitment_id: int) -> Commitment | None:
        """Fetch a commitment by its primary key."""

        def handler(session: Session) -> Commitment | None:
            return session.get(Commitment, commitment_id)

        return self._execute(handler)

    def update(
        self,
        commitment_id: int,
        updates: CommitmentUpdateInput,
        *,
        now: datetime | None = None,
        allow_state_change: bool = False,
    ) -> Commitment:
        """Update a commitment record by ID."""

        def handler(session: Session) -> Commitment:
            commitment = _fetch_commitment(session, commitment_id)
            affects_urgency = _updates_affect_urgency(updates)
            _apply_updates(commitment, updates, allow_state_change=allow_state_change)
            timestamp = _normalize_timestamp(now or datetime.now(timezone.utc))
            commitment.updated_at = timestamp
            if affects_urgency:
                normalized_due_by = _normalize_optional_timestamp(commitment.due_by)
                commitment.urgency = compute_urgency(
                    commitment.importance,
                    commitment.effort_provided,
                    normalized_due_by,
                    timestamp,
                )
                commitment.last_modified_at = timestamp
                _maybe_log_urgency_warning(
                    commitment.commitment_id,
                    commitment.urgency,
                    session=session,
                    now=timestamp,
                )
            session.flush()
            return commitment

        return self._execute(handler)

    def delete(self, commitment_id: int) -> None:
        """Delete a commitment record by ID."""

        def handler(session: Session) -> None:
            commitment = _fetch_commitment(session, commitment_id)
            session.delete(commitment)
            session.flush()
            return None

        self._execute(handler)

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


def _fetch_commitment(session: Session, commitment_id: int) -> Commitment:
    """Return a commitment or raise when missing."""
    commitment = session.get(Commitment, commitment_id)
    if commitment is None:
        raise ValueError(f"Commitment not found: {commitment_id}")
    return commitment


def _apply_updates(
    commitment: Commitment,
    updates: CommitmentUpdateInput,
    *,
    allow_state_change: bool = False,
) -> None:
    """Apply updates to a commitment instance."""
    if updates.description is not UNSET:
        commitment.description = updates.description
    if updates.provenance_id is not UNSET:
        commitment.provenance_id = updates.provenance_id
    if updates.state is not UNSET:
        if not allow_state_change:
            raise ValueError("Commitment state updates must use the transition service.")
        commitment.state = updates.state
    if updates.importance is not UNSET:
        commitment.importance = updates.importance
    if updates.effort_provided is not UNSET:
        commitment.effort_provided = updates.effort_provided
    if updates.effort_inferred is not UNSET:
        commitment.effort_inferred = updates.effort_inferred
    if updates.urgency is not UNSET:
        commitment.urgency = updates.urgency
    if updates.due_by is not UNSET:
        commitment.due_by = _normalize_due_by(updates.due_by)
    if updates.last_progress_at is not UNSET:
        commitment.last_progress_at = _normalize_optional_timestamp(updates.last_progress_at)
    if updates.last_modified_at is not UNSET:
        commitment.last_modified_at = _normalize_optional_timestamp(updates.last_modified_at)
    if updates.ever_missed_at is not UNSET:
        commitment.ever_missed_at = _normalize_optional_timestamp(updates.ever_missed_at)
    if updates.presented_for_review_at is not UNSET:
        commitment.presented_for_review_at = _normalize_optional_timestamp(
            updates.presented_for_review_at
        )
    if updates.reviewed_at is not UNSET:
        commitment.reviewed_at = _normalize_optional_timestamp(updates.reviewed_at)
    if updates.next_schedule_id is not UNSET:
        commitment.next_schedule_id = updates.next_schedule_id


def _normalize_due_by(value: date | datetime | None) -> datetime | None:
    """Normalize due_by to UTC, converting date-only values to local 23:59:59."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _normalize_timestamp(value)
    local_timezone = get_local_timezone()
    local_due_by = datetime.combine(value, time(23, 59, 59), tzinfo=local_timezone)
    return local_due_by.astimezone(timezone.utc)


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize a datetime value to UTC."""
    return to_utc(value)


def _normalize_optional_timestamp(value: datetime | None) -> datetime | None:
    """Normalize optional datetime values to UTC when provided."""
    if value is None:
        return None
    return _normalize_timestamp(value)


def _updates_affect_urgency(updates: CommitmentUpdateInput) -> bool:
    """Return True when the update touches urgency-affecting fields."""
    return (
        updates.importance is not UNSET
        or updates.effort_provided is not UNSET
        or updates.due_by is not UNSET
    )


def _maybe_log_urgency_warning(
    commitment_id: int,
    urgency: int,
    *,
    session: Session,
    now: datetime,
) -> None:
    """Log warnings when urgent commitments have distant schedules."""
    if urgency < 95:
        return
    from commitments.schedule_link_service import CommitmentScheduleLinkService

    schedule_service = CommitmentScheduleLinkService(lambda: session)
    schedule_id = schedule_service.get_active_schedule_id_in_session(session, commitment_id)
    if schedule_id is None:
        return
    schedule = session.get(Schedule, schedule_id)
    if schedule is None or schedule.state != "active" or schedule.next_run_at is None:
        return
    schedule_time = _normalize_schedule_time(schedule.next_run_at)
    if schedule_time - now > timedelta(hours=48):
        logger.warning(
            "High urgency commitment has distant schedule: commitment_id=%s urgency=%s schedule_time=%s",
            commitment_id,
            urgency,
            schedule_time,
        )


def _normalize_schedule_time(value: datetime) -> datetime:
    """Normalize schedule times for UTC comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
