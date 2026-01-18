"""Unit tests for attention batch scheduling."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, time, timezone

from sqlalchemy.orm import sessionmaker

from attention.batch_scheduler import BatchScheduleConfig, schedule_batches
from models import AttentionBatch, AttentionBatchLog


def test_daily_schedule_creates_batch(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure daily schedules create a batch at the configured time."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    config = BatchScheduleConfig(daily_time=time(9, 0))

    with closing(session_factory()) as session:
        result = schedule_batches(session, "user", config, now)
        session.commit()

        batch = session.query(AttentionBatch).first()
        log = session.query(AttentionBatchLog).first()

    assert result.decision == "BATCH_CREATED"
    assert batch is not None
    assert batch.batch_type == "daily"
    assert log is not None
    assert log.batch_id == batch.id


def test_weekly_schedule_creates_batch(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure weekly schedules create a batch at the configured time."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    config = BatchScheduleConfig(weekly_day=now.weekday(), weekly_time=time(9, 0))

    with closing(session_factory()) as session:
        result = schedule_batches(session, "user", config, now)
        session.commit()

        batch = session.query(AttentionBatch).filter_by(batch_type="weekly").first()

    assert result.decision == "BATCH_CREATED"
    assert batch is not None
    assert batch.batch_type == "weekly"


def test_misconfigured_schedule_falls_back_to_log_only(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure misconfigured schedules fall back to LOG_ONLY."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    config = BatchScheduleConfig(weekly_day=8, weekly_time=time(9, 0))

    with closing(session_factory()) as session:
        result = schedule_batches(session, "user", config, now)

    assert result.decision == "LOG_ONLY"
    assert result.batch_ids == []
