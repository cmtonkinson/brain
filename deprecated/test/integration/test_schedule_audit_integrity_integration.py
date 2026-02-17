"""Integration tests validating schedule audit integrity."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from models import ScheduleAuditLog
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service import ScheduleCommandServiceImpl
from scheduler.schedule_service_interface import (
    ActorContext,
    ScheduleAuditListRequest,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleDefinitionInput,
    ScheduleRunNowRequest,
    ScheduleUpdateRequest,
    TaskIntentInput,
)
from test.helpers.scheduler_adapter_stub import RecordingSchedulerAdapter
from test.helpers.scheduler_harness import DeterministicClock


def _actor_context(
    *,
    request_id: str,
    trace_id: str,
    reason: str,
) -> ActorContext:
    """Create a consistent actor context for schedule audits."""
    return ActorContext(
        actor_type="human",
        actor_id="integration-user",
        channel="signal",
        trace_id=trace_id,
        request_id=request_id,
        reason=reason,
    )


def _create_schedule_request() -> ScheduleCreateRequest:
    """Return a standard create request for an interval schedule."""
    return ScheduleCreateRequest(
        task_intent=TaskIntentInput(
            summary="Audit integrity check",
            details="Ensure audit logs are complete.",
        ),
        schedule_type="interval",
        timezone="UTC",
        definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
    )


def test_schedule_audit_integrity_records_mutations_and_actor_context(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Verify audit logs capture CRUD + run-now and include actor metadata."""
    clock = DeterministicClock(datetime(2025, 1, 5, 9, 0, tzinfo=timezone.utc))
    adapter = RecordingSchedulerAdapter()
    service = ScheduleCommandServiceImpl(
        sqlite_session_factory,
        adapter,
        now_provider=clock.provider(),
    )

    create_actor = _actor_context(
        request_id="req-create",
        trace_id="trace-create",
        reason="initial creation",
    )
    create_time = clock.current
    create_result = service.create_schedule(
        _create_schedule_request(),
        create_actor,
    )

    clock.advance(minutes=1)
    update_time = clock.current
    update_actor = _actor_context(
        request_id="req-update",
        trace_id="trace-update",
        reason="adjust timezone",
    )
    update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            timezone="America/New_York",
        ),
        update_actor,
    )
    duplicate_update_result = service.update_schedule(
        ScheduleUpdateRequest(
            schedule_id=create_result.schedule.id,
            timezone="America/New_York",
        ),
        update_actor,
    )
    assert duplicate_update_result.audit_log_id == update_result.audit_log_id

    clock.advance(minutes=1)
    run_now_time = clock.current
    run_now_actor = _actor_context(
        request_id="req-run-now",
        trace_id="trace-run-now",
        reason="manual trigger",
    )
    run_now_result = service.run_now(
        ScheduleRunNowRequest(schedule_id=create_result.schedule.id),
        run_now_actor,
    )

    clock.advance(minutes=1)
    delete_time = clock.current
    delete_actor = _actor_context(
        request_id="req-delete",
        trace_id="trace-delete",
        reason="cancel after validation",
    )
    delete_result = service.delete_schedule(
        ScheduleDeleteRequest(schedule_id=create_result.schedule.id),
        delete_actor,
    )

    with closing(sqlite_session_factory()) as session:
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )
        update_audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=create_result.schedule.id, event_type="update")
            .all()
        )

    assert len(audits) == 4
    assert [audit.event_type for audit in audits] == ["create", "update", "run_now", "delete"]
    assert len(update_audits) == 1
    assert update_result.audit_log_id == update_audits[0].id
    assert delete_result.audit_log_id == audits[-1].id

    audit_map = {audit.event_type: audit for audit in audits}
    create_audit = audit_map["create"]
    update_audit = audit_map["update"]
    run_now_audit = audit_map["run_now"]
    delete_audit = audit_map["delete"]

    assert create_audit.task_intent_id == create_result.task_intent.id
    assert create_audit.actor_channel == "signal"
    assert create_audit.actor_type == "human"
    assert create_audit.trace_id == "trace-create"
    assert create_audit.request_id == "req-create"
    assert create_audit.reason == "initial creation"
    assert create_audit.diff_summary is not None
    assert create_audit.occurred_at == create_time
    assert create_result.audit_log_id == create_audit.id

    assert update_audit.actor_channel == "signal"
    assert update_audit.trace_id == "trace-update"
    assert update_audit.request_id == "req-update"
    assert update_audit.reason == "adjust timezone"
    assert update_audit.diff_summary == "timezone"
    assert update_audit.occurred_at == update_time
    assert update_result.audit_log_id == update_audit.id

    assert run_now_audit.actor_type == "human"
    assert run_now_audit.trace_id == "trace-run-now"
    assert run_now_audit.request_id == "req-run-now"
    assert run_now_audit.reason == "manual trigger"
    assert run_now_audit.diff_summary == "run_now"
    assert run_now_result.audit_log_id == run_now_audit.id
    assert run_now_audit.occurred_at == run_now_time

    assert delete_audit.actor_id == "integration-user"
    assert delete_audit.trace_id == "trace-delete"
    assert delete_audit.reason == "cancel after validation"
    assert delete_audit.occurred_at == delete_time
    assert delete_result.audit_log_id == delete_audit.id

    query_service = ScheduleQueryServiceImpl(sqlite_session_factory)
    all_audits = query_service.list_schedule_audits(
        ScheduleAuditListRequest(schedule_id=create_result.schedule.id)
    )
    assert len(all_audits.audit_logs) == 4
    assert all_audits.next_cursor is None
    assert all_audits.audit_logs[0].event_type == "delete"
    assert all_audits.audit_logs[0].trace_id == "trace-delete"

    run_now_filter = query_service.list_schedule_audits(
        ScheduleAuditListRequest(
            schedule_id=create_result.schedule.id,
            event_type="run_now",
        )
    )
    assert len(run_now_filter.audit_logs) == 1
    assert run_now_filter.audit_logs[0].request_id == "req-run-now"
