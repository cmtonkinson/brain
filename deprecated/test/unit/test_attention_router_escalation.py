"""Unit tests for attention router escalation behavior."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.envelope_schema import (
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    SignalPayload,
)
from attention.router import AttentionRouter
from attention.storage import record_notification_history
from attention.escalation import EscalationLevel
from models import AttentionEscalationLog


class FakeSignalClient:
    """Stub Signal client that records sends."""

    def __init__(self) -> None:
        """Initialize an empty send log."""
        self.sent: list[str] = []

    async def send_message(
        self,
        from_number: str,
        to_number: str,
        message: str,
        *,
        source_component: str = "unknown",
    ) -> bool:
        """Record outbound message and return success."""
        self.sent.append(message)
        return True


@pytest.mark.asyncio
async def test_ignored_twice_escalates_to_signal(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure repeated ignored signals escalate to Signal."""
    session_factory = sqlite_session_factory
    signal_reference = "signal:ignored"
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        record_notification_history(
            session,
            owner="user",
            signal_reference=signal_reference,
            outcome="LOG_ONLY",
            channel=None,
            decided_at=now,
        )
        record_notification_history(
            session,
            owner="user",
            signal_reference=signal_reference,
            outcome="LOG_ONLY",
            channel=None,
            decided_at=now,
        )
        session.commit()

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="status.update",
        signal_reference=signal_reference,
        actor="user",
        owner="user",
        channel_hint="signal",
        urgency=0.1,
        channel_cost=0.9,
        content_type="status",
        timestamp=now,
        signal_payload=SignalPayload(
            from_number="+15550000000",
            to_number="+15551234567",
            message="hello",
        ),
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="agent",
            origin_signal=signal_reference,
            confidence=0.5,
            provenance=[
                ProvenanceInput(
                    input_type="test",
                    reference="ignored",
                    description="ignored signal",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)
    assert result.decision == "ESCALATE:signal"

    with closing(session_factory()) as session:
        logs = session.query(AttentionEscalationLog).all()

    assert len(logs) == 1


@pytest.mark.asyncio
async def test_deadline_escalates_when_window_is_reached(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure approaching deadlines trigger escalation."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    deadline = now + timedelta(minutes=30)

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="status.update",
        signal_reference="signal:deadline",
        actor="user",
        owner="user",
        channel_hint="signal",
        urgency=0.1,
        channel_cost=0.9,
        content_type="status",
        timestamp=now,
        deadline=deadline,
        signal_payload=SignalPayload(
            from_number="+15550000000",
            to_number="+15551234567",
            message="deadline",
        ),
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="agent",
            origin_signal="signal:deadline",
            confidence=0.4,
            provenance=[
                ProvenanceInput(
                    input_type="test",
                    reference="deadline",
                    description="deadline signal",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)
    assert result.decision == "ESCALATE:signal"

    with closing(session_factory()) as session:
        logs = session.query(AttentionEscalationLog).all()

    assert len(logs) == 1


@pytest.mark.asyncio
async def test_severity_increase_escalates(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure increasing severity triggers escalation."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="status.update",
        signal_reference="signal:severity",
        actor="user",
        owner="user",
        channel_hint="signal",
        urgency=0.1,
        channel_cost=0.9,
        content_type="status",
        timestamp=now,
        previous_severity=1,
        current_severity=2,
        signal_payload=SignalPayload(
            from_number="+15550000000",
            to_number="+15551234567",
            message="severity",
        ),
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="agent",
            origin_signal="signal:severity",
            confidence=0.4,
            provenance=[
                ProvenanceInput(
                    input_type="test",
                    reference="severity",
                    description="severity signal",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)
    assert result.decision == "ESCALATE:signal"

    with closing(session_factory()) as session:
        logs = session.query(AttentionEscalationLog).all()

    assert len(logs) == 1


@pytest.mark.asyncio
async def test_escalation_level_rolls_forward_across_signals(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure escalation level increments based on prior signal type history."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        session.add(
            AttentionEscalationLog(
                owner="user",
                signal_type="status.update",
                signal_reference="signal:previous",
                trigger="ignored_repeatedly",
                level=int(EscalationLevel.LOW),
                timestamp=now,
            )
        )
        session.commit()

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="status.update",
        signal_reference="signal:new",
        actor="user",
        owner="user",
        channel_hint="signal",
        urgency=0.1,
        channel_cost=0.9,
        content_type="status",
        timestamp=now + timedelta(minutes=5),
        deadline=now + timedelta(minutes=30),
        signal_payload=SignalPayload(
            from_number="+15550000000",
            to_number="+15551234567",
            message="roll-forward",
        ),
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="agent",
            origin_signal="signal:new",
            confidence=0.4,
            provenance=[
                ProvenanceInput(
                    input_type="test",
                    reference="roll-forward",
                    description="roll-forward escalation",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)
    assert result.decision == "ESCALATE:signal"

    with closing(session_factory()) as session:
        record = (
            session.query(AttentionEscalationLog)
            .filter_by(owner="user", signal_type="status.update")
            .order_by(AttentionEscalationLog.timestamp.desc())
            .first()
        )

    assert record is not None
    assert record.signal_reference == "signal:new"
    assert record.level == int(EscalationLevel.MEDIUM)
