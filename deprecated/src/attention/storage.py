"""Storage accessors for attention context and notification history."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import AttentionContextWindow, NotificationHistoryEntry
from time_utils import get_local_timezone, to_utc

logger = logging.getLogger(__name__)

DND_START = time(21, 0)
DND_END = time(5, 0)


@dataclass(frozen=True)
class AttentionContextSnapshot:
    """Resolved attention context window for a specific timestamp."""

    owner: str
    interruptible: bool
    source: str
    window_start: datetime | None
    window_end: datetime | None


@dataclass(frozen=True)
class HistoryCount:
    """Aggregated history count grouped by channel and outcome."""

    channel: str | None
    outcome: str
    count: int


def _normalize_timestamp(value: datetime, label: str) -> datetime:
    """Ensure timestamps are timezone-aware, defaulting to UTC if naive."""
    if value.tzinfo is None:
        logger.warning("Naive timestamp provided for %s; assuming UTC.", label)
        return value.replace(tzinfo=timezone.utc)
    return value


def _validate_window(start_at: datetime, end_at: datetime) -> None:
    """Validate that a time window has a positive duration."""
    if start_at >= end_at:
        logger.error("Invalid time window: start_at must be before end_at.")
        raise ValueError("start_at must be before end_at.")


def create_attention_context_window(
    session: Session,
    owner: str,
    source: str,
    start_at: datetime,
    end_at: datetime,
    interruptible: bool,
) -> AttentionContextWindow:
    """Persist a new attention context window after validation."""
    if not owner.strip():
        logger.error("Owner is required for attention context windows.")
        raise ValueError("owner is required.")
    if not source.strip():
        logger.error("Source is required for attention context windows.")
        raise ValueError("source is required.")
    start_at = _normalize_timestamp(start_at, "start_at")
    end_at = _normalize_timestamp(end_at, "end_at")
    _validate_window(start_at, end_at)

    window = AttentionContextWindow(
        owner=owner.strip(),
        source=source.strip(),
        start_at=start_at,
        end_at=end_at,
        interruptible=interruptible,
    )
    session.add(window)
    session.flush()
    return window


def get_attention_context_for_timestamp(
    session: Session,
    owner: str,
    timestamp: datetime,
) -> AttentionContextSnapshot:
    """Fetch the attention context window that covers the given timestamp."""
    timestamp = _normalize_timestamp(timestamp, "timestamp")
    query = (
        session.query(AttentionContextWindow)
        .filter(AttentionContextWindow.owner == owner)
        .filter(AttentionContextWindow.start_at <= timestamp)
        .filter(AttentionContextWindow.end_at > timestamp)
        .order_by(AttentionContextWindow.start_at.desc())
    )
    window = query.first()
    if window is None:
        logger.warning("No attention context for owner=%s at %s.", owner, timestamp)
        window = _create_default_context_window(session, owner, timestamp)
        session.flush()
        return AttentionContextSnapshot(
            owner=window.owner,
            interruptible=window.interruptible,
            source=window.source,
            window_start=_normalize_timestamp(window.start_at, "window_start"),
            window_end=_normalize_timestamp(window.end_at, "window_end"),
        )
    return AttentionContextSnapshot(
        owner=window.owner,
        interruptible=window.interruptible,
        source=window.source,
        window_start=_normalize_timestamp(window.start_at, "window_start"),
        window_end=_normalize_timestamp(window.end_at, "window_end"),
    )


def _create_default_context_window(
    session: Session,
    owner: str,
    timestamp: datetime,
) -> AttentionContextWindow:
    """Create a default context window using a static DND range."""
    local_tz = get_local_timezone()
    local_timestamp = timestamp.astimezone(local_tz)
    local_time = local_timestamp.time()
    if local_time >= DND_START or local_time < DND_END:
        dnd_start, dnd_end = _resolve_dnd_bounds(local_timestamp, local_tz)
        start_at = dnd_start
        end_at = dnd_end
        interruptible = False
        source = "default_dnd"
    else:
        local_date = local_timestamp.date()
        start_at = datetime.combine(local_date, DND_END, tzinfo=local_tz)
        end_at = datetime.combine(local_date, DND_START, tzinfo=local_tz)
        interruptible = True
        source = "default_daytime"

    # TODO: Merge skill-derived context (e.g., calendar events) into these windows.
    return create_attention_context_window(
        session,
        owner=owner,
        source=source,
        start_at=to_utc(start_at),
        end_at=to_utc(end_at),
        interruptible=interruptible,
    )


def _resolve_dnd_bounds(
    timestamp: datetime,
    local_tz: ZoneInfo,
) -> tuple[datetime, datetime]:
    """Return the local DND window that surrounds the timestamp."""
    local_date = timestamp.date()
    start = datetime.combine(local_date, DND_START, tzinfo=local_tz)
    end = datetime.combine(local_date, DND_END, tzinfo=local_tz)
    if timestamp.time() < DND_END:
        start -= timedelta(days=1)
        end = datetime.combine(local_date, DND_END, tzinfo=local_tz)
    elif timestamp.time() >= DND_START:
        end += timedelta(days=1)
    else:
        end = datetime.combine(local_date + timedelta(days=1), DND_END, tzinfo=local_tz)
    return start, end


def get_notification_history_count_for_signal(
    session: Session,
    owner: str,
    signal_reference: str,
    outcomes: Iterable[str] | None = None,
) -> int:
    """Return the count of history entries for a signal reference."""
    try:
        query = (
            session.query(func.count(NotificationHistoryEntry.id))
            .filter(NotificationHistoryEntry.owner == owner)
            .filter(NotificationHistoryEntry.signal_reference == signal_reference)
        )
        if outcomes:
            query = query.filter(NotificationHistoryEntry.outcome.in_(list(outcomes)))
        return int(query.scalar() or 0)
    except Exception:
        logger.exception("Failed to query history for signal=%s.", signal_reference)
        return 0


def record_notification_history(
    session: Session,
    owner: str,
    signal_reference: str,
    outcome: str,
    channel: str | None,
    decided_at: datetime | None = None,
) -> NotificationHistoryEntry:
    """Persist a notification history entry for a routed signal."""
    if not owner.strip():
        logger.error("Owner is required for notification history.")
        raise ValueError("owner is required.")
    if not signal_reference.strip():
        logger.error("Signal reference is required for notification history.")
        raise ValueError("signal_reference is required.")
    if not outcome.strip():
        logger.error("Outcome is required for notification history.")
        raise ValueError("outcome is required.")

    decided_at = _normalize_timestamp(decided_at or datetime.now(timezone.utc), "decided_at")
    entry = NotificationHistoryEntry(
        owner=owner.strip(),
        signal_reference=signal_reference.strip(),
        outcome=outcome.strip(),
        channel=channel.strip() if channel else None,
        created_at=decided_at,
    )
    session.add(entry)
    session.flush()
    return entry


def get_notification_history_counts(
    session: Session,
    owner: str,
    start_at: datetime,
    end_at: datetime,
    channels: Iterable[str] | None = None,
    outcomes: Iterable[str] | None = None,
) -> list[HistoryCount]:
    """Return aggregated history counts within a time window."""
    start_at = _normalize_timestamp(start_at, "start_at")
    end_at = _normalize_timestamp(end_at, "end_at")
    _validate_window(start_at, end_at)

    try:
        query = (
            session.query(
                NotificationHistoryEntry.channel,
                NotificationHistoryEntry.outcome,
                func.count(NotificationHistoryEntry.id),
            )
            .filter(NotificationHistoryEntry.owner == owner)
            .filter(NotificationHistoryEntry.created_at >= start_at)
            .filter(NotificationHistoryEntry.created_at < end_at)
        )
        if channels:
            query = query.filter(NotificationHistoryEntry.channel.in_(list(channels)))
        if outcomes:
            query = query.filter(NotificationHistoryEntry.outcome.in_(list(outcomes)))
        query = query.group_by(
            NotificationHistoryEntry.channel,
            NotificationHistoryEntry.outcome,
        )
        rows = query.all()
    except Exception:
        logger.exception("Failed to query notification history.")
        return []

    return [HistoryCount(channel=row[0], outcome=row[1], count=row[2]) for row in rows]
