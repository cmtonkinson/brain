"""Unit tests for attention router gate enforcement."""

from __future__ import annotations

import pytest

from attention.router import AttentionRouter, OutboundSignal
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
async def test_router_invoked_for_all_components() -> None:
    """Ensure signals from all components pass through the router."""
    router = AttentionRouter(signal_client=FakeSignalClient())
    sources = ["scheduled_task", "watcher", "skill", "memory", "agent"]

    for source in sources:
        await router.route_signal(
            OutboundSignal(
                source_component=source,
                channel="signal",
                from_number="+15550000000",
                to_number="+15551234567",
                message="hello",
            )
        )

    routed = router.routed_signals()
    assert [item.source_component for item in routed] == sources


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
async def test_router_batch_handles_mixed_sources() -> None:
    """Ensure mixed source batches route through the router."""
    router = AttentionRouter(signal_client=FakeSignalClient())
    signals = [
        OutboundSignal(
            source_component="scheduled_task",
            channel="signal",
            from_number="+15550000000",
            to_number="+15551230000",
            message="one",
        ),
        OutboundSignal(
            source_component="skill",
            channel="signal",
            from_number="+15550000000",
            to_number="+15551230001",
            message="two",
        ),
    ]

    for signal in signals:
        await router.route_signal(signal)

    assert len(router.routed_signals()) == 2
