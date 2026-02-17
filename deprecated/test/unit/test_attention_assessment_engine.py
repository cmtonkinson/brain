"""Unit tests for the attention assessment engine."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.assessment_engine import (
    BaseAssessmentOutcome,
    assess_base_signal,
)
from attention.audit import AttentionAuditLogger
from attention.storage import create_attention_context_window
from models import AttentionAuditLog, BatchedSignal, DeferredSignal


def test_high_urgency_high_confidence_notifies(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure high urgency and confidence notify immediately."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner="user",
            source="calendar",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
            interruptible=True,
        )
        assessment = assess_base_signal(
            session,
            {
                "signal_reference": "signal-1",
                "owner": "user",
                "source_component": "scheduler",
                "urgency": 0.95,
                "confidence": 0.9,
                "channel_cost": 0.2,
                "channel": "signal",
                "timestamp": now,
            },
        )
        session.commit()

        deferred = session.query(DeferredSignal).all()
        batched = session.query(BatchedSignal).all()

    assert assessment.outcome == BaseAssessmentOutcome.NOTIFY
    assert deferred == []
    assert batched == []


def test_low_urgency_quiet_hours_batches(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure low urgency during quiet hours defers or batches."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 23, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner="user",
            source="quiet-hours",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
            interruptible=False,
        )
        assessment = assess_base_signal(
            session,
            {
                "signal_reference": "signal-2",
                "owner": "user",
                "source_component": "scheduler",
                "urgency": 0.2,
                "confidence": 0.8,
                "channel_cost": 0.4,
                "channel": "signal",
                "timestamp": now,
                "topic": "ops",
                "category": "low",
            },
        )
        session.commit()

        batched = session.query(BatchedSignal).first()

    assert assessment.outcome == BaseAssessmentOutcome.BATCH
    assert batched is not None
    assert batched.topic == "ops"
    assert batched.category == "low"


def test_missing_fields_return_safe_fallback(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure missing input fields return a safe fallback and log errors."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        assessment = assess_base_signal(session, {"owner": "user"})

    assert assessment.outcome == BaseAssessmentOutcome.SUPPRESS
    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_base_assessment_logged_before_policy(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure base assessments are logged even if policy changes later."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner="user",
            source="calendar",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
            interruptible=True,
        )
        audit_logger = AttentionAuditLogger(session)
        assessment = assess_base_signal(
            session,
            {
                "signal_reference": "signal-3",
                "owner": "user",
                "source_component": "scheduler",
                "urgency": 0.5,
                "confidence": 0.9,
                "channel_cost": 0.3,
                "channel": "signal",
                "timestamp": now,
            },
            audit_logger=audit_logger,
        )
        session.commit()

        record = session.query(AttentionAuditLog).first()

    assert assessment.outcome in {
        BaseAssessmentOutcome.NOTIFY,
        BaseAssessmentOutcome.BATCH,
        BaseAssessmentOutcome.DEFER,
    }
    assert record is not None
    assert record.event_type == "BASE_ASSESSMENT"


def test_deferred_assessment_writes_holding_area(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure deferred assessments persist with reevaluation timestamps."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner="user",
            source="calendar",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
            interruptible=True,
        )
        assessment = assess_base_signal(
            session,
            {
                "signal_reference": "signal-4",
                "owner": "user",
                "source_component": "scheduler",
                "urgency": 0.4,
                "confidence": 0.2,
                "channel_cost": 0.2,
                "channel": "signal",
                "timestamp": now,
            },
            reevaluate_after=timedelta(minutes=15),
        )
        session.commit()

        deferred = session.query(DeferredSignal).first()

    assert assessment.outcome == BaseAssessmentOutcome.DEFER
    assert deferred is not None
    assert deferred.reevaluate_at == (now + timedelta(minutes=15)).replace(tzinfo=None)
