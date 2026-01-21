"""Integration tests for the schedule command service."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from models import Schedule, ScheduleAuditLog, TaskIntent
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleUpdateRequest,
    ScheduleRunNowRequest,
    ScheduleDefinitionInput,
    ScheduleValidationError,
    TaskIntentInput,
)
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-abc",
        request_id="req-123",
        reason="integration-test",
    )


def test_schedule_service_create_update_delete_happy_path(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure create/update/delete flows succeed through the command service."""
    now = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    adapter = RecordingSchedulerAdapter()
    service = ScheduleCommandServiceImpl(sqlite_session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()

    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Daily review",
                details="Review outstanding tasks.",
            ),
            schedule_type="interval",
            timezone="UTC",
            definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )

    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            definition=ScheduleDefinitionInput(interval_count=2, interval_unit="day"),
        ),
        actor,
    )

    run_now_result = service.run_now(
        ScheduleRunNowRequest(schedule_id=create_result.schedule.id),
        actor,
    )

    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=create_result.schedule.id),
        actor,
    )

    assert create_result.audit_log_id is not None
    assert update_result.audit_log_id is not None
    assert run_now_result.audit_log_id is not None
    assert delete_result.state == "canceled"

    with closing(sqlite_session_factory()) as session:
        stored = session.query(Schedule).filter_by(id=create_result.schedule.id).one()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert stored.state == "canceled"
    assert [audit.event_type for audit in audits] == ["create", "update", "run_now", "delete"]
    assert adapter.registered[0].schedule_id == create_result.schedule.id
    assert adapter.updated[0].schedule_id == create_result.schedule.id
    assert adapter.triggered[0][0] == create_result.schedule.id
    assert adapter.deleted[0] == create_result.schedule.id


def test_schedule_service_lifecycle_updates_metadata_and_audits(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure schedule lifecycle updates metadata without altering task intent."""
    now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)
    adapter = RecordingSchedulerAdapter()
    service = ScheduleCommandServiceImpl(sqlite_session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()

    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(
                summary="Weekly sync",
                details="Coordinate weekly updates.",
            ),
            schedule_type="interval",
            timezone="UTC",
            definition=ScheduleDefinitionInput(interval_count=1, interval_unit="week"),
        ),
        actor,
    )

    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            timezone="America/New_York",
        ),
        actor,
    )

    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=create_result.schedule.id),
        actor,
    )

    with closing(sqlite_session_factory()) as session:
        schedule = session.query(Schedule).filter_by(id=create_result.schedule.id).one()
        intent = session.query(TaskIntent).filter_by(id=create_result.task_intent.id).one()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )
        create_audit = session.get(ScheduleAuditLog, create_result.audit_log_id)
        update_audit = session.get(ScheduleAuditLog, update_result.audit_log_id)
        delete_audit = session.get(ScheduleAuditLog, delete_result.audit_log_id)

    assert intent.summary == "Weekly sync"
    assert schedule.task_intent_id == intent.id
    assert schedule.timezone == "America/New_York"
    assert schedule.state == "canceled"
    assert [audit.event_type for audit in audits] == ["create", "update", "delete"]
    assert create_audit is not None and create_audit.event_type == "create"
    assert update_audit is not None and update_audit.event_type == "update"
    assert delete_audit is not None and delete_audit.event_type == "delete"


def test_schedule_service_update_rejects_invalid_timezone(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure invalid timezone updates fail without creating audit entries."""
    now = datetime(2025, 1, 3, 8, 0, tzinfo=timezone.utc)
    adapter = RecordingSchedulerAdapter()
    service = ScheduleCommandServiceImpl(sqlite_session_factory, adapter, now_provider=lambda: now)
    actor = _actor_context()

    create_result = service.create_schedule(
        ScheduleCreateRequest(
            task_intent=TaskIntentInput(summary="Morning brief"),
            schedule_type="interval",
            timezone="UTC",
            definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )

    try:
        service.update_schedule(
            ScheduleUpdateRequest(
                schedule_id=create_result.schedule.id,
                timezone="Not/AZone",
            ),
            actor,
        )
    except ScheduleValidationError:
        pass
    else:
        raise AssertionError("Expected ScheduleValidationError for invalid timezone.")

    with closing(sqlite_session_factory()) as session:
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert [audit.event_type for audit in audits] == ["create"]
