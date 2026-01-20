"""Integration test for dispatcher invocation with attention routing."""

from __future__ import annotations

import asyncio
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone

from attention.envelope_schema import NotificationEnvelope, ProvenanceInput, RoutingEnvelope
from attention.envelope_schema import RoutingIntent
from attention.router import AttentionRouter
from models import Schedule
from scheduler import data_access
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)


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


@dataclass
class _AgentInvoker:
    """Invoker that routes notifications through the attention router."""

    router: AttentionRouter
    calls: list[ExecutionInvocationRequest]

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Route a notification and return a successful invocation result."""
        envelope = RoutingEnvelope(
            version="1.0.0",
            signal_type="scheduled.notification",
            signal_reference=f"scheduled:{request.execution.id}",
            actor="scheduled",
            owner="scheduled",
            channel_hint="signal",
            urgency=0.2,
            channel_cost=0.4,
            content_type="message",
            routing_intent=RoutingIntent.LOG_ONLY,
            notification=NotificationEnvelope(
                version="1.0.0",
                source_component="scheduled_task",
                origin_signal=f"scheduled:{request.execution.id}",
                confidence=0.7,
                provenance=[
                    ProvenanceInput(
                        input_type="schedule",
                        reference=str(request.execution.schedule_id),
                        description="Scheduled execution notification.",
                    )
                ],
            ),
        )
        asyncio.run(self.router.route_envelope(envelope))
        self.calls.append(request)
        return ExecutionInvocationResult(
            status="success",
            result_code="ok",
            attention_required=True,
            message="Routed scheduled notification.",
        )


def _seed_schedule(session) -> Schedule:
    """Create and return a schedule for dispatcher integration tests."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="tester",
        channel="cli",
        trace_id="trace-seed",
        request_id="req-seed",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Integration schedule"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    return schedule


def test_dispatcher_invokes_agent_and_routes_attention(
    sqlite_session_factory,
) -> None:
    """Ensure dispatcher invokes agent and routes notifications through attention router."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_schedule(session)
        session.commit()

    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=sqlite_session_factory,
    )
    invoker = _AgentInvoker(router=router, calls=[])
    dispatcher = ExecutionDispatcher(sqlite_session_factory, invoker)
    scheduled_for = datetime(2025, 2, 7, 10, 0, tzinfo=timezone.utc)

    dispatcher.dispatch(
        DispatcherCallbackPayload(
            schedule_id=schedule.id,
            scheduled_for=scheduled_for,
            trace_id="callback-router",
            emitted_at=scheduled_for,
        )
    )

    assert len(invoker.calls) == 1
    assert router.routed_sources() == ["scheduled_task"]
