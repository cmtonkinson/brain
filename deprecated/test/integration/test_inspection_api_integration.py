"""Integration tests for inspection API queries and audit linkage."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from scheduler import data_access
from scheduler.data_access import (
    PredicateEvaluationAuditInput,
    record_predicate_evaluation_audit,
)
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import (
    ExecutionAuditListRequest,
    ExecutionListRequest,
    PredicateEvaluationAuditListRequest,
    ScheduleAuditListRequest,
    ScheduleGetRequest,
    ScheduleListRequest,
)


def _seed_schedule(session: Session) -> data_access.Schedule:
    """Create an interval schedule with an inline task intent."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="inspection",
        channel="cli",
        trace_id="trace-inspect",
        request_id="req-inspect",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Inspection schedule"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    session.flush()
    return schedule


def _create_execution(
    session: Session, schedule: data_access.Schedule, trace_id: str, status: str
) -> data_access.Execution:
    """Persist an execution record for the provided schedule."""
    actor = data_access.ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id=trace_id,
        request_id=f"req-{trace_id}",
        actor_context="scheduled|inspection",
    )
    execution = data_access.create_execution(
        session,
        data_access.ExecutionCreateInput(
            task_intent_id=schedule.task_intent_id,
            schedule_id=schedule.id,
            scheduled_for=datetime(2025, 1, 5, 9, tzinfo=timezone.utc),
            status=status,
        ),
        actor,
    )
    return execution


def test_inspection_queries_include_schedule_executions_and_audit_data(
    sqlite_session_factory,
) -> None:
    """Ensure the inspection API surfaces return schedule, execution, and audit linkage."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_schedule(session)
        first_exec = _create_execution(session, schedule, "trace-first-exec", status="succeeded")
        _create_execution(session, schedule, "trace-second-exec", status="failed")
        audit_input = PredicateEvaluationAuditInput(
            evaluation_id="eval-inspection-001",
            schedule_id=schedule.id,
            execution_id=first_exec.id,
            task_intent_id=schedule.task_intent_id,
            actor_type="scheduled",
            actor_id=None,
            actor_channel="scheduled",
            actor_privilege_level="constrained",
            actor_autonomy_level="limited",
            trace_id="trace-predicate-inspection",
            request_id="req-predicate-inspection",
            predicate_subject="obsidian.read",
            predicate_operator="exists",
            predicate_value=None,
            predicate_value_type="string",
            evaluation_time=datetime(2025, 1, 5, 9, tzinfo=timezone.utc),
            evaluated_at=datetime(2025, 1, 5, 9, tzinfo=timezone.utc),
            status="true",
            result_code="evaluated",
            message="Predicate evaluated to true.",
            observed_value="true",
            error_code=None,
            error_message=None,
            authorization_decision="allow",
            authorization_reason_code=None,
            authorization_reason_message=None,
            authorization_policy_name=None,
            authorization_policy_version=None,
            provider_name="test-scheduler",
            provider_attempt=1,
            correlation_id="trace-predicate-inspection",
        )
        record_predicate_evaluation_audit(session, audit_input)
        session.commit()
        schedule_id = schedule.id

    query_service = ScheduleQueryServiceImpl(sqlite_session_factory)
    schedule_result = query_service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))
    assert schedule_result.schedule.id == schedule.id

    list_result = query_service.list_schedules(ScheduleListRequest(limit=10))
    assert any(item.id == schedule_id for item in list_result.schedules)

    schedule_audit = query_service.list_schedule_audits(
        ScheduleAuditListRequest(schedule_id=schedule_id, limit=1)
    )
    assert schedule_audit.audit_logs
    assert schedule_audit.audit_logs[0].event_type == "create"

    executions = query_service.list_executions(ExecutionListRequest(schedule_id=schedule_id))
    assert len(executions.executions) >= 2

    execution_audit = query_service.list_execution_audits(
        ExecutionAuditListRequest(schedule_id=schedule_id)
    )
    assert execution_audit.audit_logs
    assert any(entry.status in {"succeeded", "failed"} for entry in execution_audit.audit_logs)

    predicate_audit = query_service.list_predicate_evaluation_audits(
        PredicateEvaluationAuditListRequest(schedule_id=schedule_id)
    )
    assert len(predicate_audit.audit_logs) == 1
    assert predicate_audit.audit_logs[0].evaluation_id == "eval-inspection-001"
