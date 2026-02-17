"""Unit tests for suppressed signal reviews."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from attention.escalation import EscalationLevel
from attention.suppressed_review import (
    apply_review_action,
    create_suppressed_review_batch,
)
from models import AttentionEscalationLog, AttentionReviewLog, NotificationHistoryEntry


def test_suppressed_signals_included_in_review_batch(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure suppressed signals appear in review batches."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add(
            NotificationHistoryEntry(
                owner="user",
                signal_reference="signal-1",
                outcome="SUPPRESS",
                channel=None,
                created_at=now - timedelta(minutes=5),
            )
        )
        session.commit()

        result = create_suppressed_review_batch(
            session, "user", since=now - timedelta(hours=1), now=now
        )
        session.commit()

    assert result.batch_id is not None
    assert len(result.items) == 1
    assert result.items[0].signal_reference == "signal-1"


def test_review_action_triggers_escalation(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure review actions can trigger escalation."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        result = apply_review_action(
            session,
            owner="user",
            signal_reference="signal-2",
            action="escalate",
            current_level=EscalationLevel.LOW,
            timestamp=now,
        )
        session.commit()

        escalation = session.query(AttentionEscalationLog).first()

    assert result.escalation is not None
    assert escalation is not None
    assert escalation.trigger == "review_escalation"


def test_missing_suppressed_signals_logs_noop_review(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure empty reviews log a no-op action."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        result = create_suppressed_review_batch(
            session, "user", since=now - timedelta(hours=1), now=now
        )
        session.commit()

        log = session.query(AttentionReviewLog).first()

    assert result.items == []
    assert log is not None
    assert log.action == "noop"
