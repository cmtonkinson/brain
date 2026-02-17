"""Unit tests for escalation evaluation."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.escalation import (
    EscalationDecision,
    EscalationInput,
    EscalationLevel,
    evaluate_escalation,
    record_escalation_decision,
)
from models import AttentionEscalationLog


def test_repeated_ignores_trigger_escalation() -> None:
    """Ensure repeated ignores trigger escalation step-up."""
    inputs = EscalationInput(
        owner="user",
        signal_type="status.update",
        signal_reference="signal-1",
        current_level=EscalationLevel.LOW,
        ignored_count=3,
        ignore_threshold=2,
    )
    decision = evaluate_escalation(inputs)

    assert decision.escalated is True
    assert decision.level == EscalationLevel.MEDIUM
    assert decision.trigger == "ignored_repeatedly"


def test_approaching_deadline_triggers_escalation() -> None:
    """Ensure approaching deadlines increase escalation level."""
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    inputs = EscalationInput(
        owner="user",
        signal_type="status.update",
        signal_reference="signal-2",
        current_level=EscalationLevel.LOW,
        deadline=now + timedelta(minutes=30),
        deadline_window=timedelta(hours=1),
        timestamp=now,
    )
    decision = evaluate_escalation(inputs)

    assert decision.escalated is True
    assert decision.level == EscalationLevel.MEDIUM
    assert decision.trigger == "approaching_deadline"


def test_missing_metadata_prevents_escalation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure missing escalation metadata prevents escalation."""
    inputs = EscalationInput(
        owner="user",
        signal_type="status.update",
        signal_reference="signal-3",
        current_level=EscalationLevel.LOW,
    )
    decision = evaluate_escalation(inputs)

    assert decision.escalated is False
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_escalation_log_includes_trigger_and_timestamp(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure escalation logs include trigger and timestamp."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    inputs = EscalationInput(
        owner="user",
        signal_type="status.update",
        signal_reference="signal-4",
        current_level=EscalationLevel.LOW,
        ignored_count=5,
        ignore_threshold=2,
        timestamp=now,
    )
    decision = EscalationDecision(
        escalated=True,
        level=EscalationLevel.MEDIUM,
        trigger="ignored_repeatedly",
    )
    with closing(session_factory()) as session:
        record_escalation_decision(session, inputs, decision)
        session.commit()

        record = session.query(AttentionEscalationLog).first()

    assert record is not None
    assert record.trigger == "ignored_repeatedly"
    assert record.timestamp == now.replace(tzinfo=None)
