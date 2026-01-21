"""Integration tests for predicate evaluation audit integrity."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import PredicateEvaluationAuditLog
from scheduler import data_access
from scheduler.predicate_evaluation import PredicateEvaluationService
from scheduler.predicate_evaluation_audit import PredicateEvaluationAuditRecorder
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import PredicateEvaluationAuditListRequest


class _StaticSubjectResolver:
    """Simple resolver that returns a constant value for a subject."""

    def resolve(self, subject: str, actor_context: object) -> str | int | float | bool | None:  # noqa: ARG002
        return "ready"


def _seed_conditional_schedule(session: Session) -> data_access.Schedule:
    """Create a conditional schedule for predicate evaluation audits."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="predicate-test",
        channel="cli",
        trace_id="trace-predicate-seed",
        request_id="req-predicate-seed",
    )
    _, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Predicate audit"),
            schedule_type="conditional",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(
                predicate_subject="obsidian.read",
                predicate_operator="exists",
                evaluation_interval_count=1,
                evaluation_interval_unit="minute",
            ),
        ),
        actor,
    )
    session.flush()
    return schedule


def test_predicate_audit_records_and_queries_are_idempotent(sqlite_session_factory) -> None:
    """Verify predicate audit entries include actor context, timestamps, and remain idempotent."""
    with closing(sqlite_session_factory()) as session:
        schedule = _seed_conditional_schedule(session)
        session.commit()
        schedule_id = schedule.id

    evaluation_time = datetime(2025, 9, 1, 8, tzinfo=timezone.utc)
    resolver = _StaticSubjectResolver()
    audit_recorder = PredicateEvaluationAuditRecorder(sqlite_session_factory)
    service = PredicateEvaluationService(
        session_factory=sqlite_session_factory,
        subject_resolver=resolver,
        audit_recorder=audit_recorder,
        now_provider=lambda: evaluation_time,
    )

    result = service.evaluate_schedule(
        schedule_id=schedule_id,
        evaluation_id="eval-ideal-001",
        evaluation_time=evaluation_time,
        provider_name="test-scheduler",
        provider_attempt=1,
        trace_id="trace-predicate-integration",
    )
    assert result.status.name == "TRUE"

    duplicate_result = service.evaluate_schedule(
        schedule_id=schedule_id,
        evaluation_id="eval-ideal-001",
        evaluation_time=evaluation_time,
        provider_name="test-scheduler",
        provider_attempt=1,
        trace_id="trace-predicate-integration",
    )
    assert duplicate_result.status.name == "TRUE"

    with closing(sqlite_session_factory()) as session:
        audits = (
            session.query(PredicateEvaluationAuditLog)
            .filter(PredicateEvaluationAuditLog.schedule_id == schedule_id)
            .all()
        )
    assert len(audits) == 1
    audit = audits[0]
    assert audit.trace_id == "trace-predicate-integration"
    assert audit.task_intent_id == schedule.task_intent_id
    assert audit.actor_type == "scheduled"

    query_service = ScheduleQueryServiceImpl(sqlite_session_factory)
    audit_list = query_service.list_predicate_evaluation_audits(
        PredicateEvaluationAuditListRequest(schedule_id=schedule_id)
    )
    assert len(audit_list.audit_logs) == 1
    assert audit_list.audit_logs[0].evaluation_id == "eval-ideal-001"
