"""Persistence helpers for attention deferred and batched signals."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import BatchedSignal, DeferredSignal


def record_deferred_signal(
    session: Session,
    owner: str,
    signal_reference: str,
    source_component: str,
    reason: str,
    reevaluate_at: datetime,
) -> DeferredSignal:
    """Persist a deferred signal entry."""
    entry = DeferredSignal(
        owner=owner,
        signal_reference=signal_reference,
        source_component=source_component,
        reason=reason,
        reevaluate_at=reevaluate_at,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)
    session.flush()
    return entry


def record_batched_signal(
    session: Session,
    owner: str,
    signal_reference: str,
    source_component: str,
    topic: str,
    category: str,
) -> BatchedSignal:
    """Persist a batched signal entry."""
    entry = BatchedSignal(
        owner=owner,
        signal_reference=signal_reference,
        source_component=source_component,
        topic=topic,
        category=category,
        created_at=datetime.now(timezone.utc),
    )
    session.add(entry)
    session.flush()
    return entry
