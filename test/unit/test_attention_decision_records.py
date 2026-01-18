"""Unit tests for attention decision record persistence."""

from __future__ import annotations

from contextlib import closing

import pytest
from sqlalchemy.orm import sessionmaker

from attention.decision_records import DecisionRecordInput, persist_decision_record
from models import AttentionDecisionRecord


def test_decision_persistence_succeeds(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure decision persistence returns a record id."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        result = persist_decision_record(
            session,
            DecisionRecordInput(
                signal_reference="signal-1",
                channel="signal",
                base_assessment="NOTIFY",
                policy_outcome=None,
                final_decision="NOTIFY:signal",
                explanation="ok",
            ),
        )
        session.commit()

        record = session.get(AttentionDecisionRecord, result.record_id)

    assert result.record_id is not None
    assert record is not None


def test_decision_persistence_failure_returns_log_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure persistence failures return LOG_ONLY and log errors."""

    class FailingSession:
        """Session stub that raises on persistence."""

        def add(self, *args, **kwargs) -> None:
            """Raise an error to simulate persistence failure."""
            raise RuntimeError("boom")

        def flush(self) -> None:
            """No-op flush for failing session."""
            return None

    result = persist_decision_record(
        FailingSession(),
        DecisionRecordInput(
            signal_reference="signal-2",
            channel="signal",
            base_assessment="NOTIFY",
            policy_outcome=None,
            final_decision="NOTIFY:signal",
            explanation="ok",
        ),
    )

    assert result.decision == "LOG_ONLY"
    assert any(record.levelname == "ERROR" for record in caplog.records)
