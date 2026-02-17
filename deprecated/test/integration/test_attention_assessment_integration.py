"""Integration tests for attention assessment with storage accessors."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from attention.assessment_engine import BaseAssessmentOutcome, assess_base_signal
from attention.storage import create_attention_context_window, record_notification_history


def test_assessment_engine_uses_context_and_history(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure assessment engine consumes storage queries to affect outcomes."""
    session_factory = sqlite_session_factory
    owner = "user"
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner=owner,
            source="calendar",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
            interruptible=True,
        )
        record_notification_history(
            session,
            owner=owner,
            signal_reference="signal-1",
            outcome=BaseAssessmentOutcome.NOTIFY.value,
            channel="signal",
            decided_at=now - timedelta(minutes=5),
        )
        session.commit()

        assessment = assess_base_signal(
            session,
            {
                "signal_reference": "signal-2",
                "owner": owner,
                "source_component": "scheduler",
                "urgency": 0.4,
                "confidence": 0.9,
                "channel_cost": 0.5,
                "channel": "signal",
                "timestamp": now,
            },
            history_window=timedelta(minutes=30),
        )

    assert assessment.outcome == BaseAssessmentOutcome.BATCH
