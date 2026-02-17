"""Aggregation helpers for daily batch reminder content."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from models import Commitment
from time_utils import to_utc

DEFAULT_BATCH_LOOKAHEAD_HOURS = 48


def list_batch_due_commitments(
    session_factory: Callable[[], Session],
    *,
    now: datetime | None = None,
    lookahead_hours: int = DEFAULT_BATCH_LOOKAHEAD_HOURS,
) -> list[Commitment]:
    """Return OPEN commitments due within the batch lookahead window."""
    if lookahead_hours < 0:
        raise ValueError("lookahead_hours must be non-negative.")
    timestamp = to_utc(now or datetime.now(timezone.utc))
    window_end = timestamp + timedelta(hours=lookahead_hours)
    with session_factory() as session:
        rows = (
            session.query(Commitment)
            .filter(
                Commitment.state == "OPEN",
                Commitment.due_by.is_not(None),
                Commitment.due_by >= timestamp,
                Commitment.due_by <= window_end,
            )
            .order_by(Commitment.urgency.desc())
            .all()
        )
        return list(rows)


__all__ = [
    "DEFAULT_BATCH_LOOKAHEAD_HOURS",
    "list_batch_due_commitments",
]
