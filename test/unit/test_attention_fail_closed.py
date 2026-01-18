"""Unit tests for fail-closed routing behavior."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.audit import AttentionAuditLogger
from attention.fail_closed import FailClosedConfig, FailClosedRouter
from attention.router import AttentionRouter, OutboundSignal
from models import AttentionFailClosedQueue


class FakeSignalClient:
    """Stub Signal client for fail-closed tests."""

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
        """Record a message send."""
        self.sent.append(message)
        return True


@pytest.mark.asyncio
async def test_router_unavailable_queues_signal(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure router unavailability defaults to LOG_ONLY and queues signals."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        audit_logger = AttentionAuditLogger(session)
        router = AttentionRouter(
            signal_client=FakeSignalClient(),
            session_factory=session_factory,
        )
        fail_closed = FailClosedRouter(router, session, audit_logger)
        signal = OutboundSignal(
            source_component="agent",
            channel="signal",
            from_number="+15550000000",
            to_number="+15551234567",
            message="hello",
        )

        result = await fail_closed.route(
            signal,
            router_available=False,
            policy_available=True,
            now=now,
        )
        session.commit()

        queued = session.query(AttentionFailClosedQueue).all()

    assert result.decision == "LOG_ONLY"
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_policy_unavailable_queues_signal(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure policy unavailability defaults to LOG_ONLY and queues signals."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        audit_logger = AttentionAuditLogger(session)
        router = AttentionRouter(
            signal_client=FakeSignalClient(),
            session_factory=session_factory,
        )
        fail_closed = FailClosedRouter(router, session, audit_logger)
        signal = OutboundSignal(
            source_component="agent",
            channel="signal",
            from_number="+15550000000",
            to_number="+15551234567",
            message="hello",
        )

        result = await fail_closed.route(
            signal,
            router_available=True,
            policy_available=False,
            now=now,
        )
        session.commit()

        queued = session.query(AttentionFailClosedQueue).all()

    assert result.decision == "LOG_ONLY"
    assert len(queued) == 1


@pytest.mark.asyncio
async def test_recovery_reprocesses_queued_signals(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure queued signals are reprocessed when the router recovers."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        signal_client = FakeSignalClient()
        audit_logger = AttentionAuditLogger(session)
        router = AttentionRouter(
            signal_client=signal_client,
            session_factory=session_factory,
        )
        fail_closed = FailClosedRouter(
            router,
            session,
            audit_logger,
            config=FailClosedConfig(retry_delay=timedelta(minutes=1)),
        )
        signal = OutboundSignal(
            source_component="agent",
            channel="signal",
            from_number="+15550000000",
            to_number="+15551234567",
            message="hello",
        )

        await fail_closed.route(
            signal,
            router_available=False,
            policy_available=True,
            now=now,
        )
        session.commit()

        processed = await fail_closed.reprocess_queue(now + timedelta(minutes=2))
        session.commit()

    assert processed == 1
    assert len(signal_client.sent) == 1
    assert signal_client.sent[0].startswith("hello")


@pytest.mark.asyncio
async def test_router_pipeline_failure_queues_signal(
    sqlite_session_factory: sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure router pipeline failures queue signals for retry."""
    session_factory = sqlite_session_factory

    def _raise_assessment(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("attention.router.assess_base_signal", _raise_assessment)

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    signal = OutboundSignal(
        source_component="agent",
        channel="signal",
        from_number="+15550000000",
        to_number="+15551234567",
        message="hello",
    )

    result = await router.route_signal(signal)
    with closing(session_factory()) as session:
        queued = session.query(AttentionFailClosedQueue).all()

    assert result.decision == "LOG_ONLY"
    assert len(queued) == 1
