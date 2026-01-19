"""Unit tests for attention router decision overrides."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, time, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.envelope_schema import (
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    RoutingIntent,
    SignalPayload,
)
from attention.router import AttentionRouter
from models import AttentionDoNotDisturb, AttentionAlwaysNotify


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
async def test_always_notify_overrides_dnd_policy(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure always-notify preference overrides DND policy outcomes."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 22, 30, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add(
            AttentionDoNotDisturb(
                owner="user",
                start_time=time(22, 0),
                end_time=time(6, 0),
                timezone="UTC",
            )
        )
        session.add(
            AttentionAlwaysNotify(
                owner="user",
                signal_type="status.update",
                source_component="scheduler",
            )
        )
        session.commit()

    signal_client = FakeSignalClient()
    router = AttentionRouter(
        signal_client=signal_client,
        session_factory=session_factory,
    )
    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="status.update",
        signal_reference="signal:override",
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
            message="override",
        ),
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="scheduler",
            origin_signal="signal:override",
            confidence=0.3,
            provenance=[
                ProvenanceInput(
                    input_type="test",
                    reference="override",
                    description="always notify override",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)

    assert result.decision == "NOTIFY:signal"
    assert signal_client.sent


@pytest.mark.asyncio
async def test_log_only_persistence_failure_fails_closed(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure log-only routing failures return LOG_ONLY with an error."""
    session_factory = sqlite_session_factory
    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )

    def _raise_persist(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("attention.router.persist_decision_record", _raise_persist)

    envelope = RoutingEnvelope(
        version="1.0.0",
        signal_type="test.signal",
        signal_reference="log-only-fail",
        actor="+15550000000",
        owner="+15551234567",
        channel_hint="signal",
        urgency=0.2,
        channel_cost=0.4,
        content_type="message",
        routing_intent=RoutingIntent.LOG_ONLY,
        notification=NotificationEnvelope(
            version="1.0.0",
            source_component="scheduler",
            origin_signal="log-only-fail",
            confidence=0.7,
            provenance=[
                ProvenanceInput(
                    input_type="signal",
                    reference="log-only-fail",
                    description="test",
                )
            ],
        ),
    )

    result = await router.route_envelope(envelope)

    assert result.decision == "LOG_ONLY"
    assert result.error is not None
