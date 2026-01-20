"""Integration test for Celery callback bridge invocation flow."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from models import Schedule
from scheduler import data_access
from scheduler.adapters.celery_callback_bridge import (
    CeleryCallbackRequest,
    handle_celery_callback,
)
from scheduler.callback_bridge import CallbackBridge, DispatcherCallbackPayload


@dataclass
class _DispatcherStub:
    """Dispatcher stub that persists executions."""

    session_factory: Callable[[], Session]

    def dispatch(self, payload: DispatcherCallbackPayload) -> None:
        """Persist an execution record for the callback payload."""
        actor = data_access.ExecutionActorContext(
            actor_type="scheduled",
            actor_id=None,
            channel="scheduled",
            trace_id="trace-dispatch",
            request_id="req-dispatch",
            correlation_id=payload.correlation_id,
        )
        with closing(self.session_factory()) as session:
            schedule = session.query(Schedule).filter(Schedule.id == payload.schedule_id).first()
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


def _seed_schedule(session) -> Schedule:
    """Create and return a schedule for callback integration tests."""
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


def test_celery_callback_invokes_dispatcher(
    sqlite_session_factory,
) -> None:
    """Ensure Celery callback handling dispatches and persists execution."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_schedule(session)
        session.commit()

    dispatcher = _DispatcherStub(sqlite_session_factory)
    bridge = CallbackBridge(sqlite_session_factory, dispatcher)
    emitted_at = datetime(2025, 2, 1, 8, 0, tzinfo=timezone.utc)

    result = handle_celery_callback(
        CeleryCallbackRequest(
            schedule_id=schedule.id,
            scheduled_for=None,
            correlation_id="cb-integration",
            emitted_at=emitted_at,
            provider_attempt=1,
            provider_task_id="celery-task-99",
        ),
        bridge,
    )

    with closing(sqlite_session_factory()) as session:
        execution = data_access.get_execution_by_correlation_id(
            session,
            schedule.id,
            "cb-integration",
        )

    assert result.status == "accepted"
    assert execution is not None
