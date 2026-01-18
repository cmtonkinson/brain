"""Unit tests for attention explanations and summaries."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.explanations import generate_explanation, generate_usage_summary
from models import AttentionAuditLog


def test_explanation_generation_returns_response(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure explanation generation returns a response for logged notifications."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add(
            AttentionAuditLog(
                event_type="NOTIFICATION",
                source_component="scheduler",
                signal_reference="signal-1",
                base_assessment="NOTIFY",
                policy_outcome=None,
                final_decision="NOTIFY:signal",
                timestamp=now,
            )
        )
        session.commit()

        explanation = generate_explanation(session, "signal-1")

    assert explanation is not None
    assert "final=NOTIFY:signal" in explanation


def test_summary_generation_returns_aggregate_report(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure summary generation returns an aggregated report."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add_all(
            [
                AttentionAuditLog(
                    event_type="NOTIFICATION",
                    source_component="scheduler",
                    signal_reference="signal-1",
                    base_assessment="NOTIFY",
                    policy_outcome=None,
                    final_decision="NOTIFY:signal",
                    timestamp=now,
                ),
                AttentionAuditLog(
                    event_type="NOTIFICATION",
                    source_component="scheduler",
                    signal_reference="signal-2",
                    base_assessment="LOG_ONLY",
                    policy_outcome=None,
                    final_decision="LOG_ONLY",
                    timestamp=now,
                ),
            ]
        )
        session.commit()

        summary = generate_usage_summary(
            session,
            owner="user",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(hours=1),
        )

    assert summary is not None
    assert "NOTIFY:signal" in summary
    assert "LOG_ONLY" in summary


def test_disabled_mode_returns_no_output(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure disabled mode returns no output and logs a no-op."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        explanation = generate_explanation(session, "signal-1", enabled=False)
        summary = generate_usage_summary(
            session,
            owner="user",
            start_at=now - timedelta(hours=1),
            end_at=now,
            enabled=False,
        )

    assert explanation is None
    assert summary is None
    assert any(record.levelname == "INFO" for record in caplog.records)
