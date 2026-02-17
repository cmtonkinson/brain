"""Unit tests for attention audit logging."""

from __future__ import annotations

from contextlib import closing

from sqlalchemy.orm import sessionmaker

from attention.audit import AttentionAuditLogger
from models import AttentionAuditLog, NotificationEnvelope


def test_signal_log_includes_required_fields(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure signal log entries capture required fields."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        logger = AttentionAuditLogger(session)
        ok = logger.log_signal(
            source_component="scheduler",
            signal_reference="signal-123",
            base_assessment="DEFER",
            policy_outcome=None,
            final_decision="LOG_ONLY",
        )
        session.commit()

        record = session.query(AttentionAuditLog).first()

    assert ok is True
    assert record is not None
    assert record.source_component == "scheduler"
    assert record.signal_reference == "signal-123"
    assert record.base_assessment == "DEFER"
    assert record.final_decision == "LOG_ONLY"


def test_routing_log_includes_required_fields(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure routing log entries include assessment and policy data."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        logger = AttentionAuditLogger(session)
        ok = logger.log_routing(
            source_component="scheduler",
            signal_reference="signal-456",
            base_assessment="BATCH",
            policy_outcome="DEFER",
            final_decision="DEFER",
        )
        session.commit()

        record = session.query(AttentionAuditLog).first()

    assert ok is True
    assert record is not None
    assert record.base_assessment == "BATCH"
    assert record.policy_outcome == "DEFER"
    assert record.final_decision == "DEFER"


def test_notification_log_links_envelope(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure notification logs link to a persisted envelope."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        envelope = NotificationEnvelope(
            version="1.0.0",
            source_component="scheduler",
            origin_signal="task.completed",
            confidence=0.9,
        )
        session.add(envelope)
        session.flush()
        envelope_id = envelope.id

        logger = AttentionAuditLogger(session)
        ok = logger.log_notification(
            source_component="scheduler",
            signal_reference="signal-789",
            base_assessment="NOTIFY",
            policy_outcome=None,
            final_decision="NOTIFY:signal",
            envelope_id=envelope_id,
        )
        session.commit()

        record = session.query(AttentionAuditLog).first()

    assert ok is True
    assert record is not None
    assert record.envelope_id == envelope_id


def test_logging_failure_does_not_raise() -> None:
    """Ensure logging failures are captured without raising."""

    class FailingSession:
        """Session stub that raises on add."""

        def add(self, *args, **kwargs):
            """Raise an error to simulate persistence failure."""
            raise RuntimeError("boom")

        def flush(self):
            """No-op flush for the failing session."""
            return None

    logger = AttentionAuditLogger(FailingSession())
    ok = logger.log_signal(
        source_component="scheduler",
        signal_reference="signal-999",
        base_assessment="DEFER",
        policy_outcome=None,
        final_decision="LOG_ONLY",
    )

    assert ok is False
