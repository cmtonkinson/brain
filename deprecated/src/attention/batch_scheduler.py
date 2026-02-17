"""Batch scheduling for attention routing digests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from models import AttentionBatch, AttentionBatchLog, BatchedSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BatchScheduleConfig:
    """Configuration for batch schedules."""

    daily_time: time | None = None
    weekly_day: int | None = None
    weekly_time: time | None = None


@dataclass(frozen=True)
class BatchCreationResult:
    """Result of batch scheduling."""

    decision: str
    batch_ids: list[int]
    error: str | None = None


def schedule_batches(
    session: Session,
    owner: str,
    config: BatchScheduleConfig,
    now: datetime,
) -> BatchCreationResult:
    """Create scheduled batches or fall back to LOG_ONLY on errors."""
    try:
        batch_ids: list[int] = []
        if config.daily_time is not None:
            daily = _create_daily_batch(session, owner, config.daily_time, now)
            if daily:
                batch_ids.append(daily.id)
        if config.weekly_day is not None or config.weekly_time is not None:
            weekly = _create_weekly_batch(
                session, owner, config.weekly_day, config.weekly_time, now
            )
            if weekly:
                batch_ids.append(weekly.id)
        batch_ids.extend(_create_topic_batches(session, owner, now))
        return BatchCreationResult(decision="BATCH_CREATED", batch_ids=batch_ids)
    except Exception as exc:
        logger.exception("Batch scheduling failed.")
        return BatchCreationResult(decision="LOG_ONLY", batch_ids=[], error=str(exc))


def _create_daily_batch(
    session: Session, owner: str, schedule_time: time, now: datetime
) -> AttentionBatch | None:
    """Create a daily batch when the schedule time is reached."""
    if schedule_time.tzinfo is not None:
        raise ValueError("daily_time must be naive time value.")
    scheduled_for = datetime.combine(now.date(), schedule_time, tzinfo=now.tzinfo)
    if now < scheduled_for:
        return None
    existing = (
        session.query(AttentionBatch)
        .filter_by(owner=owner, batch_type="daily")
        .filter(AttentionBatch.scheduled_for >= scheduled_for)
        .first()
    )
    if existing:
        return None
    batch = AttentionBatch(
        owner=owner,
        batch_type="daily",
        scheduled_for=scheduled_for,
    )
    session.add(batch)
    session.flush()
    _log_batch(session, batch.id)
    return batch


def _create_weekly_batch(
    session: Session,
    owner: str,
    weekly_day: int | None,
    weekly_time: time | None,
    now: datetime,
) -> AttentionBatch | None:
    """Create a weekly batch when the schedule time is reached."""
    if weekly_day is None or weekly_time is None:
        raise ValueError("weekly_day and weekly_time are required for weekly batches.")
    if weekly_day < 0 or weekly_day > 6:
        raise ValueError("weekly_day must be between 0 and 6.")
    if weekly_time.tzinfo is not None:
        raise ValueError("weekly_time must be naive time value.")

    days_since = (now.weekday() - weekly_day) % 7
    scheduled_date = (now - timedelta(days=days_since)).date()
    scheduled_for = datetime.combine(scheduled_date, weekly_time, tzinfo=now.tzinfo)
    if now < scheduled_for:
        return None

    week_start = scheduled_for - timedelta(days=scheduled_for.weekday())
    existing = (
        session.query(AttentionBatch)
        .filter_by(owner=owner, batch_type="weekly")
        .filter(AttentionBatch.scheduled_for >= week_start)
        .first()
    )
    if existing:
        return None
    batch = AttentionBatch(
        owner=owner,
        batch_type="weekly",
        scheduled_for=scheduled_for,
    )
    session.add(batch)
    session.flush()
    _log_batch(session, batch.id)
    return batch


def _create_topic_batches(session: Session, owner: str, now: datetime) -> list[int]:
    """Create topic batches for unassigned batched signals."""
    batches: list[int] = []
    signals = (
        session.query(BatchedSignal)
        .filter_by(owner=owner)
        .filter(BatchedSignal.batch_id.is_(None))
        .all()
    )
    grouped: dict[tuple[str, str], list[BatchedSignal]] = {}
    for signal in signals:
        grouped.setdefault((signal.topic, signal.category), []).append(signal)
    for (topic, category), group in grouped.items():
        batch = AttentionBatch(
            owner=owner,
            batch_type="topic",
            scheduled_for=now,
            topic=topic,
            category=category,
        )
        session.add(batch)
        session.flush()
        for signal in group:
            signal.batch_id = batch.id
        _log_batch(session, batch.id)
        batches.append(batch.id)
    return batches


def _log_batch(session: Session, batch_id: int) -> None:
    """Persist a batch creation log entry."""
    session.add(AttentionBatchLog(batch_id=batch_id, created_at=datetime.now(timezone.utc)))
    session.flush()
