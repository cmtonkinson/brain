"""Scheduler test harness helpers for deterministic time and execution polling."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time
from typing import Callable, Iterable

from sqlalchemy.orm import Session

from models import Execution


@dataclass
class DeterministicClock:
    """Deterministic clock for tests with manual time control."""

    current: datetime

    def __post_init__(self) -> None:
        """Normalize the initial time to a timezone-aware value."""
        if self.current.tzinfo is None:
            self.current = self.current.replace(tzinfo=timezone.utc)

    def now(self) -> datetime:
        """Return the current clock time."""
        return self.current

    def advance(
        self,
        *,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
    ) -> datetime:
        """Advance the clock by the provided delta and return the new time."""
        delta = timedelta(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
            days=days,
        )
        if delta.total_seconds() == 0:
            return self.current
        self.current = self.current + delta
        return self.current

    def set(self, value: datetime) -> datetime:
        """Set the clock to a specific time and return the new value."""
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        self.current = value
        return self.current

    def provider(self) -> Callable[[], datetime]:
        """Return a callable suitable for time injection in tests."""
        return self.now


def wait_for_execution_status(
    session_factory: Callable[[], Session],
    *,
    execution_id: int | None = None,
    schedule_id: int | None = None,
    expected_statuses: Iterable[str] | None = None,
    timeout_seconds: float = 2.0,
    poll_interval_seconds: float = 0.05,
) -> Execution:
    """Poll for an execution to reach an expected status within a timeout."""
    if (execution_id is None) == (schedule_id is None):
        raise ValueError("Provide exactly one of execution_id or schedule_id.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive.")

    statuses = tuple(expected_statuses or ("succeeded", "failed", "canceled"))
    start = time.monotonic()
    last_status: str | None = None

    while True:
        with closing(session_factory()) as session:
            execution = _fetch_execution(session, execution_id, schedule_id)
            if execution is not None:
                last_status = str(execution.status)
                if last_status in statuses:
                    _normalize_execution_timestamps(execution)
                    return execution
        if time.monotonic() - start >= timeout_seconds:
            raise TimeoutError(
                "Timed out waiting for execution to reach "
                f"{statuses}; last_status={last_status}."
            )
        time.sleep(poll_interval_seconds)


def _fetch_execution(
    session: Session,
    execution_id: int | None,
    schedule_id: int | None,
) -> Execution | None:
    """Return the latest execution for the provided identifiers."""
    if execution_id is not None:
        return session.query(Execution).filter(Execution.id == execution_id).first()
    if schedule_id is None:
        return None
    return (
        session.query(Execution)
        .filter(Execution.schedule_id == schedule_id)
        .order_by(Execution.id.desc())
        .first()
    )


def _normalize_execution_timestamps(execution: Execution) -> None:
    """Normalize execution timestamps to UTC when the database returns naive values."""
    execution.scheduled_for = _ensure_aware(execution.scheduled_for)
    execution.started_at = _ensure_aware(execution.started_at)
    execution.finished_at = _ensure_aware(execution.finished_at)


def _ensure_aware(value: datetime | None) -> datetime | None:
    """Return a timezone-aware datetime, assuming UTC when tzinfo is missing."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
