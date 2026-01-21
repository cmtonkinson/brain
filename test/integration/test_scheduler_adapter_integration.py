"""Integration tests for Celery scheduler adapter registration and callbacks."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from scheduler import data_access
from scheduler.adapters.celery_adapter import (
    CeleryAdapterConfig,
    CeleryBeatEntry,
    CeleryEtaSchedule,
    CeleryIntervalSchedule,
    CelerySchedulerAdapter,
)
from scheduler.adapters.celery_callback_bridge import CeleryCallbackRequest, handle_celery_callback
from scheduler.callback_bridge import CallbackBridge, DispatcherCallbackPayload
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDefinitionInput,
    TaskIntentInput,
)


@dataclass
class _DispatcherStub:
    """Stub dispatcher that persists executions for incoming callbacks."""

    session_factory: Callable[[], Session]

    def dispatch(self, payload: DispatcherCallbackPayload) -> None:
        """Create a matching execution record for every callback dispatched."""
        actor = data_access.ExecutionActorContext(
            actor_type="scheduled",
            actor_id=None,
            channel="scheduled",
            trace_id=payload.trace_id,
            request_id=payload.trace_id,
            actor_context="scheduled|callback",
        )
        with closing(self.session_factory()) as session:
            schedule = session.query(data_access.Schedule).filter(data_access.Schedule.id == payload.schedule_id).first()
            if schedule is None:
                raise ValueError("schedule not found for dispatcher stub.")
            data_access.create_execution(
                session,
                data_access.ExecutionCreateInput(
                    task_intent_id=schedule.task_intent_id,
                    schedule_id=schedule.id,
                    scheduled_for=payload.scheduled_for,
                ),
                actor,
            )
            session.commit()


class _RecordingCeleryClient:
    """In-memory Celery client that records adapter interactions."""

    def __init__(self) -> None:
        self.registered: list[CeleryBeatEntry] = []
        self.updated: list[CeleryBeatEntry] = []
        self.paused: list[str] = []
        self.resumed: list[str] = []
        self.deleted: list[str] = []
        self.enqueued: list[tuple[int, datetime]] = []

    def register_entry(self, entry: CeleryBeatEntry) -> None:
        self.registered.append(entry)

    def update_entry(self, entry: CeleryBeatEntry) -> None:
        self.updated.append(entry)

    def pause_entry(self, entry_name: str) -> None:
        self.paused.append(entry_name)

    def resume_entry(self, entry_name: str) -> None:
        self.resumed.append(entry_name)

    def delete_entry(self, entry_name: str) -> None:
        self.deleted.append(entry_name)

    def enqueue_callback(self, payload: object, *, eta: datetime, queue_name: str | None) -> None:  # noqa: ARG001
        self.enqueued.append((payload.schedule_id, eta))

    def check_health(self) -> bool:
        return True


def _actor_context() -> ActorContext:
    """Consistent actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="integration-user",
        channel="signal",
        trace_id="trace-adapter",
        request_id="req-adapter",
        reason="integration test",
    )


def test_scheduler_adapter_registers_with_celery_and_dispatches_callbacks(
    sqlite_session_factory,
) -> None:
    """Verify the Celery adapter registers schedules and Celery callbacks reach the dispatcher."""
    now = datetime(2025, 4, 1, 8, tzinfo=timezone.utc)
    client = _RecordingCeleryClient()
    adapter = CelerySchedulerAdapter(
        client,
        CeleryAdapterConfig(callback_task_name="scheduler.dispatch", queue_name="scheduler"),
    )
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory,
        adapter,
        now_provider=lambda: now,
    )
    actor = _actor_context()

    interval_definition = ScheduleDefinitionInput(interval_count=1, interval_unit="day")
    interval = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Interval coverage"),
            schedule_type="interval",
            timezone="UTC",
            definition=interval_definition,
        ),
        actor,
    )

    one_time = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="One-time callback"),
            schedule_type="one_time",
            timezone="UTC",
            definition=ScheduleDefinitionInput(run_at=now + timedelta(minutes=15)),
        ),
        actor,
    )

    assert len(client.registered) == 2
    entries = {entry.name: entry for entry in client.registered}
    interval_entry = entries[f"schedule:{interval.schedule.id}"]
    assert isinstance(interval_entry.schedule, CeleryIntervalSchedule)
    assert interval_entry.schedule.every == 1
    assert interval_entry.schedule.period == "days"

    one_time_entry = entries[f"schedule:{one_time.schedule.id}"]
    assert isinstance(one_time_entry.schedule, CeleryEtaSchedule)
    assert one_time_entry.kwargs["scheduled_for"] == now + timedelta(minutes=15)

    bridge = CallbackBridge(sqlite_session_factory, _DispatcherStub(sqlite_session_factory))
    callback_request = CeleryCallbackRequest(
        schedule_id=interval.schedule.id,
        scheduled_for=now + timedelta(hours=1),
        trace_id="trace-celery-adapter",
        emitted_at=now + timedelta(hours=1),
    )
    result = handle_celery_callback(callback_request, bridge)
    assert result.status == "accepted"

    with closing(sqlite_session_factory()) as session:
        execution = data_access.get_execution_by_trace_id(
            session,
            interval.schedule.id,
            "trace-celery-adapter",
        )
    assert execution is not None
