"""Aggregation queries for weekly commitment reviews."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from models import Commitment, CommitmentReviewRun, CommitmentStateTransition
from time_utils import to_utc

DEFAULT_REVIEW_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class ReviewCommitmentSets:
    """Aggregated commitment sets for a weekly review."""

    completed: list[Commitment]
    missed: list[Commitment]
    modified: list[Commitment]
    no_due_by: list[Commitment]
    last_run_at: datetime


def get_last_review_run_at(session_factory: Callable[[], Session]) -> datetime:
    """Return the most recent review run timestamp or epoch when absent."""
    with closing(session_factory()) as session:
        run = session.query(CommitmentReviewRun).order_by(CommitmentReviewRun.run_at.desc()).first()
        if run is None:
            return DEFAULT_REVIEW_EPOCH
        return _normalize_timestamp(run.run_at)


def record_review_run(
    session_factory: Callable[[], Session],
    *,
    run_at: datetime | None = None,
) -> CommitmentReviewRun:
    """Insert a review run record and return it."""
    timestamp = _normalize_timestamp(run_at or datetime.now(timezone.utc))
    with closing(session_factory()) as session:
        session.expire_on_commit = False
        try:
            record = CommitmentReviewRun(run_at=timestamp)
            session.add(record)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return record


def list_completed_commitments_since(
    session_factory: Callable[[], Session],
    *,
    since: datetime,
) -> list[Commitment]:
    """Return commitments completed since the provided timestamp."""
    since_ts = _normalize_timestamp(since)
    with closing(session_factory()) as session:
        rows = (
            session.query(Commitment)
            .join(
                CommitmentStateTransition,
                CommitmentStateTransition.commitment_id == Commitment.commitment_id,
            )
            .filter(
                CommitmentStateTransition.to_state == "COMPLETED",
                CommitmentStateTransition.transitioned_at > since_ts,
            )
            .order_by(CommitmentStateTransition.transitioned_at.asc())
            .distinct()
            .all()
        )
        return list(rows)


def list_missed_commitments_since(
    session_factory: Callable[[], Session],
    *,
    since: datetime,
) -> list[Commitment]:
    """Return commitments marked MISSED since the provided timestamp."""
    since_ts = _normalize_timestamp(since)
    with closing(session_factory()) as session:
        rows = (
            session.query(Commitment)
            .join(
                CommitmentStateTransition,
                CommitmentStateTransition.commitment_id == Commitment.commitment_id,
            )
            .filter(
                CommitmentStateTransition.to_state == "MISSED",
                CommitmentStateTransition.transitioned_at > since_ts,
            )
            .order_by(CommitmentStateTransition.transitioned_at.asc())
            .distinct()
            .all()
        )
        return list(rows)


def list_modified_commitments_since(
    session_factory: Callable[[], Session],
    *,
    since: datetime,
) -> list[Commitment]:
    """Return commitments modified since the provided timestamp."""
    since_ts = _normalize_timestamp(since)
    with closing(session_factory()) as session:
        rows = (
            session.query(Commitment)
            .filter(
                Commitment.last_modified_at.is_not(None),
                Commitment.last_modified_at > since_ts,
            )
            .order_by(Commitment.last_modified_at.asc())
            .all()
        )
        return list(rows)


def list_open_commitments_without_due_by(
    session_factory: Callable[[], Session],
) -> list[Commitment]:
    """Return OPEN commitments with no due_by set."""
    with closing(session_factory()) as session:
        rows = (
            session.query(Commitment)
            .filter(Commitment.state == "OPEN", Commitment.due_by.is_(None))
            .order_by(Commitment.commitment_id.asc())
            .all()
        )
        return list(rows)


def aggregate_review_commitments(
    session_factory: Callable[[], Session],
    *,
    since: datetime | None = None,
) -> ReviewCommitmentSets:
    """Aggregate commitment sets for review relative to the last run timestamp."""
    last_run = _normalize_timestamp(since or get_last_review_run_at(session_factory))
    return ReviewCommitmentSets(
        completed=list_completed_commitments_since(session_factory, since=last_run),
        missed=list_missed_commitments_since(session_factory, since=last_run),
        modified=list_modified_commitments_since(session_factory, since=last_run),
        no_due_by=list_open_commitments_without_due_by(session_factory),
        last_run_at=last_run,
    )


def _normalize_timestamp(value: datetime) -> datetime:
    """Normalize timestamps to UTC."""
    return to_utc(value)


__all__ = [
    "DEFAULT_REVIEW_EPOCH",
    "ReviewCommitmentSets",
    "aggregate_review_commitments",
    "get_last_review_run_at",
    "list_completed_commitments_since",
    "list_missed_commitments_since",
    "list_modified_commitments_since",
    "list_open_commitments_without_due_by",
    "record_review_run",
]
