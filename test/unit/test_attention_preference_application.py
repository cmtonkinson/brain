"""Unit tests for applying attention preferences."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, time, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.assessment_engine import BaseAssessmentOutcome
from attention.audit import AttentionAuditLogger
from attention.preference_application import (
    PreferenceApplicationInputs,
    apply_preferences,
)
from models import AttentionAlwaysNotify, AttentionAuditLog, AttentionQuietHours


def test_quiet_hours_defers_low_urgency_signal(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure quiet hours defer low-urgency signals."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 23, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        quiet = AttentionQuietHours(
            owner="user",
            start_time=time(22, 0),
            end_time=time(6, 0),
            timezone="UTC",
        )
        session.add(quiet)
        session.flush()
        quiet_id = quiet.id
        audit_logger = AttentionAuditLogger(session)

        result = apply_preferences(
            session,
            PreferenceApplicationInputs(
                owner="user",
                signal_reference="signal-1",
                source_component="scheduler",
                urgency_score=0.2,
                channel="signal",
                timestamp=now,
            ),
            BaseAssessmentOutcome.NOTIFY,
            audit_logger=audit_logger,
        )
        session.commit()

        audit = session.query(AttentionAuditLog).first()

    assert result.final_decision == BaseAssessmentOutcome.DEFER.value
    assert result.preference_reference == f"quiet_hours:{quiet_id}"
    assert audit is not None
    assert audit.preference_reference == result.preference_reference


def test_always_notify_overrides_quiet_hours(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure always-notify overrides quiet hours deferral."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 23, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add(
            AttentionQuietHours(
                owner="user",
                start_time=time(22, 0),
                end_time=time(6, 0),
                timezone="UTC",
            )
        )
        session.add(
            AttentionAlwaysNotify(
                owner="user",
                signal_type="signal-2",
                source_component="scheduler",
            )
        )
        session.commit()

        result = apply_preferences(
            session,
            PreferenceApplicationInputs(
                owner="user",
                signal_reference="signal-2",
                source_component="scheduler",
                urgency_score=0.1,
                channel="signal",
                timestamp=now,
            ),
            BaseAssessmentOutcome.DEFER,
        )

    assert result.final_decision == "NOTIFY:signal"
    assert result.preference_reference is not None


def test_missing_preferences_use_default_behavior(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure missing preferences default to the base assessment."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        result = apply_preferences(
            session,
            PreferenceApplicationInputs(
                owner="user",
                signal_reference="signal-3",
                source_component="scheduler",
                urgency_score=0.5,
                channel="signal",
                timestamp=now,
            ),
            BaseAssessmentOutcome.NOTIFY,
        )

    assert result.final_decision == "NOTIFY:signal"
    assert any(record.levelname == "WARNING" for record in caplog.records)
