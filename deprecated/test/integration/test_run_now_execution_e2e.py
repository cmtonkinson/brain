"""End-to-end integration tests for run-now execution flow."""

from __future__ import annotations

import asyncio
from contextlib import closing
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from attention.envelope_schema import (
    NotificationEnvelope,
    ProvenanceInput,
    RoutingEnvelope,
    RoutingIntent,
)
from attention.router import AttentionRouter
from models import Execution, ExecutionAuditLog, Schedule, ScheduleAuditLog
from scheduler import data_access
from scheduler.adapter_interface import AdapterHealth, SchedulePayload, SchedulerAdapter
from scheduler.callback_bridge import CallbackBridge, DispatcherCallbackPayload
from scheduler.execution_dispatcher import (
    ExecutionDispatcher,
    ExecutionInvocationRequest,
    ExecutionInvocationResult,
)
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleConflictError,
    SchedulePauseRequest,
    ScheduleRunNowRequest,
)
from test.helpers.scheduler_harness import DeterministicClock


class FakeSignalClient:
    """Stub Signal client that records outbound messages."""

    def __init__(self) -> None:
        """Initialize the sent message log."""
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
    """Invoker that routes scheduled notifications through the attention router."""

    router: AttentionRouter
    calls: list[ExecutionInvocationRequest]

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Route a scheduled notification and return a success result."""
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
                        description="Run-now execution notification.",
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
            message="Routed run-now notification.",
        )


class RunNowAdapter(SchedulerAdapter):
    """Adapter stub that triggers callbacks via the callback bridge."""

    def __init__(
        self,
        *,
        bridge: CallbackBridge,
        now_provider: Callable[[], datetime],
    ) -> None:
        """Initialize the adapter with callback bridge and clock access."""
        self._bridge = bridge
        self._now_provider = now_provider
        self.triggered: list[tuple[int, datetime, str | None, str]] = []

    def register_schedule(self, payload: SchedulePayload) -> None:
        """Ignore schedule registrations for run-now tests."""

    def update_schedule(self, payload: SchedulePayload) -> None:
        """Ignore schedule updates for run-now tests."""

    def pause_schedule(self, schedule_id: int) -> None:
        """Ignore schedule pauses for run-now tests."""

    def resume_schedule(self, schedule_id: int) -> None:
        """Ignore schedule resumes for run-now tests."""

    def delete_schedule(self, schedule_id: int) -> None:
        """Ignore schedule deletions for run-now tests."""

    def trigger_callback(
        self,
        schedule_id: int,
        scheduled_for: datetime,
        *,
        trace_id: str | None = None,
        trigger_source: str = "run_now",
    ) -> None:
        """Trigger the callback bridge for the run-now request."""
        if trace_id is None or not trace_id.strip():
            raise ValueError("trace_id is required for run-now callbacks.")
        self.triggered.append((schedule_id, scheduled_for, trace_id, trigger_source))
        payload = DispatcherCallbackPayload(
            schedule_id=schedule_id,
            scheduled_for=scheduled_for,
            trace_id=trace_id,
            emitted_at=self._now_provider(),
            trigger_source=trigger_source,
        )
        self._bridge.handle_callback(payload)

    def check_health(self) -> AdapterHealth:
        """Return a ready status for the stub adapter."""
        return AdapterHealth(status="ok", message="run-now adapter ready")


def _seed_schedule(session) -> int:
    """Create and return an active schedule for run-now tests."""
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
            task_intent=data_access.TaskIntentInput(summary="Run-now intent"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    session.flush()
    return schedule.id


def _api_actor() -> ActorContext:
    """Return a default API actor context for run-now requests."""
    return ActorContext(
        actor_type="human",
        actor_id="api-user",
        channel="signal",
        trace_id="trace-run-now",
        request_id="req-run-now",
        reason="integration-test",
    )


def _build_services(sqlite_session_factory, now_provider: Callable[[], datetime]):
    """Build the run-now adapter, callback bridge, and dispatcher stack."""
    router = AttentionRouter(
        signal_client=FakeSignalClient(),
        session_factory=sqlite_session_factory,
    )
    invoker = _AgentInvoker(router=router, calls=[])
    dispatcher = ExecutionDispatcher(
        sqlite_session_factory,
        invoker,
        now_provider=now_provider,
    )
    bridge = CallbackBridge(sqlite_session_factory, dispatcher)
    adapter = RunNowAdapter(bridge=bridge, now_provider=now_provider)
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory,
        adapter,
        now_provider=now_provider,
    )
    return adapter, service, router


def _ensure_aware(value: datetime) -> datetime:
    """Ensure a datetime is timezone-aware, defaulting to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def test_run_now_execution_end_to_end_creates_audits_and_routes_attention(
    sqlite_session_factory,
) -> None:
    """Ensure run-now triggers execution, audits, and attention routing."""
    clock = DeterministicClock(datetime(2025, 2, 7, 10, 0, tzinfo=timezone.utc))
    with closing(sqlite_session_factory()) as session:
        schedule_id = _seed_schedule(session)
        session.commit()

    adapter, service, router = _build_services(sqlite_session_factory, clock.provider())
    actor = _api_actor()
    requested_for = clock.now()

    result = service.run_now(
        ScheduleRunNowRequest(schedule_id=schedule_id, requested_for=requested_for),
        actor,
    )

    assert result.schedule_id == schedule_id
    assert adapter.triggered == [(schedule_id, requested_for, actor.trace_id, "run_now")]
    assert router.routed_sources() == ["scheduled_task"]

    with closing(sqlite_session_factory()) as session:
        execution = (
            session.query(Execution)
            .filter_by(schedule_id=schedule_id)
            .order_by(Execution.id.desc())
            .first()
        )
        assert execution is not None
        execution_audits = (
            session.query(ExecutionAuditLog)
            .filter_by(execution_id=execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )
        schedule_audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert _ensure_aware(execution.scheduled_for) == requested_for
    statuses = {str(audit.status) for audit in execution_audits}
    assert {"queued", "running", "succeeded"}.issubset(statuses)
    latest_audit = execution_audits[-1]
    assert latest_audit.actor_type == "scheduled"
    assert latest_audit.actor_channel == "scheduled"
    assert latest_audit.trace_id == actor.trace_id
    assert "run_now" in {str(audit.event_type) for audit in schedule_audits}


def test_run_now_dispatches_for_paused_schedule_and_logs_state(
    sqlite_session_factory,
) -> None:
    """Ensure run-now succeeds for paused schedules and records the paused state."""
    clock = DeterministicClock(datetime(2025, 2, 7, 12, 0, tzinfo=timezone.utc))
    with closing(sqlite_session_factory()) as session:
        schedule_id = _seed_schedule(session)
        session.commit()

    adapter, service, router = _build_services(sqlite_session_factory, clock.provider())
    actor = _api_actor()
    service.pause_schedule(
        SchedulePauseRequest(schedule_id=schedule_id, reason="maintenance"),
        actor,
    )

    requested_for = clock.now()
    result = service.run_now(
        ScheduleRunNowRequest(schedule_id=schedule_id, requested_for=requested_for),
        actor,
    )

    assert result.schedule_id == schedule_id
    assert adapter.triggered[-1] == (schedule_id, requested_for, actor.trace_id, "run_now")
    assert router.routed_sources() == ["scheduled_task"]

    with closing(sqlite_session_factory()) as session:
        schedule = session.query(Schedule).filter_by(id=schedule_id).one()
        assert str(schedule.state) == "paused"
        run_now_audit = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id, event_type="run_now")
            .order_by(ScheduleAuditLog.id.desc())
            .first()
        )

    assert run_now_audit is not None
    assert run_now_audit.diff_summary == "run_now(state=paused)"


def test_run_now_rejects_canceled_schedule_without_dispatch(
    sqlite_session_factory,
) -> None:
    """Ensure run-now fails for canceled schedules without creating executions."""
    clock = DeterministicClock(datetime(2025, 2, 7, 11, 0, tzinfo=timezone.utc))
    with closing(sqlite_session_factory()) as session:
        schedule_id = _seed_schedule(session)
        data_access.delete_schedule(
            session,
            schedule_id,
            data_access.ActorContext(
                actor_type="human",
                actor_id="tester",
                channel="cli",
                trace_id="trace-delete",
                request_id="req-delete",
                reason="cleanup",
            ),
            now=clock.now(),
        )
        session.commit()

    adapter, service, _ = _build_services(sqlite_session_factory, clock.provider())
    actor = _api_actor()

    with pytest.raises(ScheduleConflictError):
        service.run_now(
            ScheduleRunNowRequest(schedule_id=schedule_id, requested_for=clock.now()),
            actor,
        )

    assert adapter.triggered == []
    with closing(sqlite_session_factory()) as session:
        execution = session.query(Execution).filter_by(schedule_id=schedule_id).first()
        schedule_audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule_id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert execution is None
    assert "run_now" not in {str(audit.event_type) for audit in schedule_audits}
