"""Unit tests for attention router gate enforcement."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from attention.envelope_schema import NotificationEnvelope, ProvenanceInput, RoutingEnvelope
from attention.router import AttentionRouter
from attention.router_gate import RouterViolationError, get_violation_recorder
from services.signal import SignalClient


class FakeSignalClient:
    """Stub Signal client that records sends."""

    def __init__(self) -> None:
        """Initialize an empty send log."""
        self.sent: list[tuple[str, str, str]] = []

    async def send_message(
        self,
        from_number: str,
        to_number: str,
        message: str,
        *,
        source_component: str = "unknown",
    ) -> bool:
        """Record outbound message and return success."""
        self.sent.append((from_number, to_number, message))
        return True


@pytest.mark.asyncio
async def test_router_invoked_for_all_components(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure signals from all components pass through the router."""
    session_factory = sqlite_session_factory
    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    sources = ["scheduled_task", "watcher", "skill", "memory", "agent"]

    for source in sources:
        await router.route_envelope(
            RoutingEnvelope(
                version="1.0.0",
                signal_type="test.signal",
                signal_reference=f"{source}-signal",
                actor="+15550000000",
                owner="+15551234567",
                channel_hint="signal",
                urgency=0.2,
                channel_cost=0.4,
                content_type="message",
                notification=NotificationEnvelope(
                    version="1.0.0",
                    source_component=source,
                    origin_signal=f"{source}-signal",
                    confidence=0.7,
                    provenance=[
                        ProvenanceInput(
                            input_type="signal",
                            reference=f"{source}-signal",
                            description="test",
                        )
                    ],
                ),
            )
        )

    routed = router.routed_sources()
    assert routed == sources


@pytest.mark.asyncio
async def test_direct_notification_is_blocked_and_logged() -> None:
    """Ensure direct notifications are blocked and logged."""
    recorder = get_violation_recorder()
    recorder.clear()
    client = SignalClient(api_url="http://signal.test")

    with pytest.raises(RouterViolationError):
        await client.send_message(
            "+15550001111",
            "+15550002222",
            "hi",
            source_component="agent",
        )

    violations = recorder.list()
    assert len(violations) == 1
    assert violations[0].source_component == "agent"


@pytest.mark.asyncio
async def test_router_batch_handles_mixed_sources(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure mixed source batches route through the router."""
    session_factory = sqlite_session_factory
    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=session_factory,
    )
    signals = ["scheduled_task", "skill"]

    for source in signals:
        await router.route_envelope(
            RoutingEnvelope(
                version="1.0.0",
                signal_type="test.signal",
                signal_reference=f"{source}-signal",
                actor="+15550000000",
                owner="+15551234567",
                channel_hint="signal",
                urgency=0.2,
                channel_cost=0.4,
                content_type="message",
                notification=NotificationEnvelope(
                    version="1.0.0",
                    source_component=source,
                    origin_signal=f"{source}-signal",
                    confidence=0.7,
                    provenance=[
                        ProvenanceInput(
                            input_type="signal",
                            reference=f"{source}-signal",
                            description="test",
                        )
                    ],
                ),
            )
        )

    assert len(router.routed_signals()) == 2
