"""Unit tests for audit log surface functionality (Task 26).

Tests cover:
- Schedule audit log querying with filtering and pagination
- Predicate evaluation audit log querying with filtering and pagination
- Query service integration for audit log access
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from scheduler.data_access import (
    ActorContext,
    ExecutionActorContext,
    ExecutionCreateInput,
    PredicateEvaluationAuditInput,
    ScheduleAuditHistoryQuery,
    ScheduleCreateInput,
    ScheduleDefinitionInput,
    ScheduleListQuery,
    TaskIntentInput,
    create_execution,
    create_schedule,
    create_task_intent,
    get_schedule,
    get_schedule_audit,
    list_schedule_audits,
    list_schedules,
    pause_schedule,
    record_predicate_evaluation_audit,
    resume_schedule,
    update_schedule,
    ScheduleUpdateInput,
    PredicateEvaluationAuditHistoryQuery,
    get_predicate_evaluation_audit,
    list_predicate_evaluation_audits,
)
from scheduler.schedule_query_service import ScheduleQueryServiceImpl
from scheduler.schedule_service_interface import (
    ExecutionAuditListRequest,
    ExecutionGetRequest,
    ExecutionListRequest,
    PredicateEvaluationAuditGetRequest,
    PredicateEvaluationAuditListRequest,
    ScheduleAuditGetRequest,
    ScheduleAuditListRequest,
    ScheduleGetRequest,
    ScheduleListRequest,
    ScheduleNotFoundError,
    TaskIntentGetRequest,
)


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-123",
        request_id=None,
        reason="testing",
    )


def _execution_actor_context() -> ExecutionActorContext:
    """Return a default actor context for execution records."""
    return ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-789",
        request_id=None,
        actor_context="scheduled-envelope",
    )


# ============================================================================
# Schedule Audit Log Querying Tests
# ============================================================================


def test_get_schedule_audit_returns_record_by_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure get_schedule_audit returns the audit record by ID."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        session.commit()

        # Find the audit log created during schedule creation
        from models import ScheduleAuditLog

        audit = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule.id)
            .first()
        )
        audit_id = audit.id

        result = get_schedule_audit(session, audit_id)
        not_found = get_schedule_audit(session, 99999)

    assert result is not None
    assert result.id == audit_id
    assert result.schedule_id == schedule.id
    assert result.event_type == "create"
    assert not_found is None


def test_list_schedule_audits_no_filters_returns_all(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits returns all audit records when no filters applied."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        # Generate multiple audit records
        pause_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-pause",
            ),
            now=now + timedelta(minutes=5),
        )
        resume_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-resume",
            ),
            now=now + timedelta(minutes=10),
        )
        session.commit()

        result = list_schedule_audits(session, ScheduleAuditHistoryQuery())

    assert len(result.audit_logs) == 3  # create, pause, resume
    # Ordered by id desc
    assert result.audit_logs[0].id > result.audit_logs[1].id


def test_list_schedule_audits_filter_by_schedule_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits filters by schedule_id."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule1 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        schedule2 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=2)),
            ),
            actor,
            now=now,
        )
        session.commit()

        result1 = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(schedule_id=schedule1.id)
        )
        result2 = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(schedule_id=schedule2.id)
        )

    assert len(result1.audit_logs) == 1
    assert result1.audit_logs[0].schedule_id == schedule1.id
    assert len(result2.audit_logs) == 1
    assert result2.audit_logs[0].schedule_id == schedule2.id


def test_list_schedule_audits_filter_by_event_type(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits filters by event_type."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 3, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        pause_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-pause",
            ),
            now=now + timedelta(minutes=5),
        )
        session.commit()

        create_result = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(event_type="create")
        )
        pause_result = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(event_type="pause")
        )

    assert len(create_result.audit_logs) == 1
    assert create_result.audit_logs[0].event_type == "create"
    assert len(pause_result.audit_logs) == 1
    assert pause_result.audit_logs[0].event_type == "pause"


def test_list_schedule_audits_filter_by_time_range(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits filters by occurred_after and occurred_before."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    base_time = datetime(2025, 1, 4, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        # Create schedules at different times
        for i in range(3):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        run_at=base_time + timedelta(hours=i + 5)
                    ),
                ),
                actor,
                now=base_time + timedelta(hours=i),
            )
        session.commit()

        # Filter: after 1 hour mark
        after_result = list_schedule_audits(
            session,
            ScheduleAuditHistoryQuery(occurred_after=base_time + timedelta(hours=1)),
        )
        # Filter: before 1 hour mark
        before_result = list_schedule_audits(
            session,
            ScheduleAuditHistoryQuery(occurred_before=base_time + timedelta(hours=1)),
        )

    assert len(after_result.audit_logs) == 2  # hours 1 and 2
    assert len(before_result.audit_logs) == 2  # hours 0 and 1


def test_list_schedule_audits_pagination_with_cursor(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits pagination works with cursor."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        # Create 5 schedules (5 audit logs)
        for i in range(5):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        run_at=now + timedelta(hours=i + 1)
                    ),
                ),
                actor,
                now=now,
            )
        session.commit()

        # First page
        page1 = list_schedule_audits(session, ScheduleAuditHistoryQuery(limit=2))
        assert len(page1.audit_logs) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(limit=2, cursor=page1.next_cursor)
        )
        assert len(page2.audit_logs) == 2
        assert page2.next_cursor is not None

        # Third page - should have 1 record
        page3 = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(limit=2, cursor=page2.next_cursor)
        )
        assert len(page3.audit_logs) == 1
        assert page3.next_cursor is None

        # Verify no overlap
        all_ids = (
            [a.id for a in page1.audit_logs]
            + [a.id for a in page2.audit_logs]
            + [a.id for a in page3.audit_logs]
        )
        assert len(all_ids) == len(set(all_ids))


def test_list_schedule_audits_invalid_event_type_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits raises ValueError for invalid event_type."""
    session_factory = sqlite_session_factory

    with closing(session_factory()) as session:
        with pytest.raises(ValueError, match="Invalid schedule audit event type"):
            list_schedule_audits(
                session, ScheduleAuditHistoryQuery(event_type="invalid_type")
            )


def test_list_schedule_audits_combined_filters(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedule_audits supports combining multiple filters."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    base_time = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=base_time,
        )
        pause_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-pause",
            ),
            now=base_time + timedelta(hours=1),
        )
        resume_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-resume",
            ),
            now=base_time + timedelta(hours=2),
        )
        session.commit()

        # Combined: schedule_id + event_type + time range
        result = list_schedule_audits(
            session,
            ScheduleAuditHistoryQuery(
                schedule_id=schedule.id,
                event_type="pause",
                occurred_after=base_time,
                occurred_before=base_time + timedelta(hours=3),
            ),
        )

    assert len(result.audit_logs) == 1
    assert result.audit_logs[0].event_type == "pause"
    assert result.audit_logs[0].schedule_id == schedule.id


# ============================================================================
# Predicate Evaluation Audit Log Querying Tests
# ============================================================================


def _create_predicate_evaluation_audit(
    session,
    schedule_id: int,
    task_intent_id: int,
    evaluation_id: str,
    evaluated_at: datetime,
    *,
    status: str = "true",
    execution_id: int | None = None,
) -> None:
    """Helper to create a predicate evaluation audit record."""
    record_predicate_evaluation_audit(
        session,
        PredicateEvaluationAuditInput(
            evaluation_id=evaluation_id,
            schedule_id=schedule_id,
            execution_id=execution_id,
            task_intent_id=task_intent_id,
            actor_type="scheduled",
            actor_id=None,
            actor_channel="scheduled",
            actor_privilege_level="standard",
            actor_autonomy_level="limited",
            trace_id=f"trace-{evaluation_id}",
            request_id=None,
            predicate_subject="skill.health",
            predicate_operator="eq",
            predicate_value="ok",
            predicate_value_type="string",
            evaluation_time=evaluated_at,
            evaluated_at=evaluated_at,
            status=status,
            result_code="OK" if status == "true" else "PREDICATE_FALSE",
            message=None,
            observed_value="ok" if status == "true" else "error",
            error_code=None,
            error_message=None,
            authorization_decision="allow",
            authorization_reason_code=None,
            authorization_reason_message=None,
            authorization_policy_name="default",
            authorization_policy_version="1.0",
            provider_name="test-provider",
            provider_attempt=1,
            correlation_id=f"corr-{evaluation_id}",
        ),
    )


def test_get_predicate_evaluation_audit_returns_record_by_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure get_predicate_evaluation_audit returns the audit record by ID."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 7, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        _create_predicate_evaluation_audit(
            session, schedule.id, intent.id, "eval-001", now
        )
        session.commit()

        # Find the audit log
        from models import PredicateEvaluationAuditLog

        audit = session.query(PredicateEvaluationAuditLog).first()
        audit_id = audit.id

        result = get_predicate_evaluation_audit(session, audit_id)
        not_found = get_predicate_evaluation_audit(session, 99999)

    assert result is not None
    assert result.id == audit_id
    assert result.evaluation_id == "eval-001"
    assert not_found is None


def test_list_predicate_evaluation_audits_no_filters(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits returns all records when no filters."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 8, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        for i in range(3):
            _create_predicate_evaluation_audit(
                session,
                schedule.id,
                intent.id,
                f"eval-{i:03d}",
                now + timedelta(hours=i),
            )
        session.commit()

        result = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery()
        )

    assert len(result.audit_logs) == 3
    # Ordered by id desc
    assert result.audit_logs[0].id > result.audit_logs[1].id


def test_list_predicate_evaluation_audits_filter_by_schedule_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits filters by schedule_id."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 9, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule1 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        schedule2 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        # Two audits for schedule1
        _create_predicate_evaluation_audit(
            session, schedule1.id, intent.id, "eval-s1-001", now
        )
        _create_predicate_evaluation_audit(
            session, schedule1.id, intent.id, "eval-s1-002", now + timedelta(hours=1)
        )
        # One audit for schedule2
        _create_predicate_evaluation_audit(
            session, schedule2.id, intent.id, "eval-s2-001", now
        )
        session.commit()

        result1 = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(schedule_id=schedule1.id)
        )
        result2 = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(schedule_id=schedule2.id)
        )

    assert len(result1.audit_logs) == 2
    assert all(a.schedule_id == schedule1.id for a in result1.audit_logs)
    assert len(result2.audit_logs) == 1
    assert result2.audit_logs[0].schedule_id == schedule2.id


def test_list_predicate_evaluation_audits_filter_by_status(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits filters by status."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 10, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        _create_predicate_evaluation_audit(
            session, schedule.id, intent.id, "eval-true", now, status="true"
        )
        _create_predicate_evaluation_audit(
            session,
            schedule.id,
            intent.id,
            "eval-false",
            now + timedelta(hours=1),
            status="false",
        )
        session.commit()

        true_result = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(status="true")
        )
        false_result = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(status="false")
        )

    assert len(true_result.audit_logs) == 1
    assert true_result.audit_logs[0].status == "true"
    assert len(false_result.audit_logs) == 1
    assert false_result.audit_logs[0].status == "false"


def test_list_predicate_evaluation_audits_filter_by_time_range(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits filters by time range."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    base_time = datetime(2025, 1, 11, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=base_time,
        )
        for i in range(3):
            _create_predicate_evaluation_audit(
                session,
                schedule.id,
                intent.id,
                f"eval-time-{i:03d}",
                base_time + timedelta(hours=i),
            )
        session.commit()

        # After 1 hour mark
        after_result = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(
                evaluated_after=base_time + timedelta(hours=1)
            ),
        )
        # Before 1 hour mark
        before_result = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(
                evaluated_before=base_time + timedelta(hours=1)
            ),
        )

    assert len(after_result.audit_logs) == 2  # hours 1 and 2
    assert len(before_result.audit_logs) == 2  # hours 0 and 1


def test_list_predicate_evaluation_audits_pagination(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits pagination works."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 12, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        for i in range(5):
            _create_predicate_evaluation_audit(
                session,
                schedule.id,
                intent.id,
                f"eval-page-{i:03d}",
                now + timedelta(hours=i),
            )
        session.commit()

        # First page
        page1 = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(limit=2)
        )
        assert len(page1.audit_logs) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(limit=2, cursor=page1.next_cursor),
        )
        assert len(page2.audit_logs) == 2
        assert page2.next_cursor is not None

        # Third page
        page3 = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(limit=2, cursor=page2.next_cursor),
        )
        assert len(page3.audit_logs) == 1
        assert page3.next_cursor is None


def test_list_predicate_evaluation_audits_invalid_status_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_predicate_evaluation_audits raises ValueError for invalid status."""
    session_factory = sqlite_session_factory

    with closing(session_factory()) as session:
        with pytest.raises(ValueError, match="Invalid predicate evaluation status"):
            list_predicate_evaluation_audits(
                session, PredicateEvaluationAuditHistoryQuery(status="invalid")
            )


# ============================================================================
# Schedule List Querying Tests
# ============================================================================


def test_list_schedules_no_filters_returns_all(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedules returns all schedules when no filters applied."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 13, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        for i in range(3):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        run_at=now + timedelta(hours=i + 1)
                    ),
                ),
                actor,
                now=now,
            )
        session.commit()

        result = list_schedules(session, ScheduleListQuery())

    assert len(result.schedules) == 3
    # Ordered by id desc
    assert result.schedules[0].id > result.schedules[1].id


def test_list_schedules_filter_by_state(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedules filters by state."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 14, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        active_sched = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        paused_sched = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        pause_schedule(
            session,
            paused_sched.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-pause",
            ),
            now=now,
        )
        session.commit()

        active_result = list_schedules(session, ScheduleListQuery(state="active"))
        paused_result = list_schedules(session, ScheduleListQuery(state="paused"))

    assert len(active_result.schedules) == 1
    assert active_result.schedules[0].id == active_sched.id
    assert len(paused_result.schedules) == 1
    assert paused_result.schedules[0].id == paused_sched.id


def test_list_schedules_filter_by_schedule_type(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedules filters by schedule_type."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        session.commit()

        one_time_result = list_schedules(
            session, ScheduleListQuery(schedule_type="one_time")
        )
        interval_result = list_schedules(
            session, ScheduleListQuery(schedule_type="interval")
        )

    assert len(one_time_result.schedules) == 1
    assert str(one_time_result.schedules[0].schedule_type) == "one_time"
    assert len(interval_result.schedules) == 1
    assert str(interval_result.schedules[0].schedule_type) == "interval"


def test_list_schedules_pagination(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_schedules pagination works with cursor."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 16, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        for i in range(5):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        run_at=now + timedelta(hours=i + 1)
                    ),
                ),
                actor,
                now=now,
            )
        session.commit()

        page1 = list_schedules(session, ScheduleListQuery(limit=2))
        assert len(page1.schedules) == 2
        assert page1.next_cursor is not None

        page2 = list_schedules(
            session, ScheduleListQuery(limit=2, cursor=page1.next_cursor)
        )
        assert len(page2.schedules) == 2
        assert page2.next_cursor is not None

        page3 = list_schedules(
            session, ScheduleListQuery(limit=2, cursor=page2.next_cursor)
        )
        assert len(page3.schedules) == 1
        assert page3.next_cursor is None


# ============================================================================
# Query Service Integration Tests
# ============================================================================


def test_query_service_get_schedule_returns_schedule_with_intent(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service returns schedule with its task intent."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 17, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        session.commit()
        schedule_id = schedule.id
        intent_id = intent.id

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.get_schedule(ScheduleGetRequest(schedule_id=schedule_id))

    assert result.schedule.id == schedule_id
    assert result.task_intent.id == intent_id
    assert result.task_intent.summary == "Test task"


def test_query_service_get_schedule_not_found_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service raises ScheduleNotFoundError for missing schedule."""
    session_factory = sqlite_session_factory
    service = ScheduleQueryServiceImpl(session_factory)

    with pytest.raises(ScheduleNotFoundError):
        service.get_schedule(ScheduleGetRequest(schedule_id=99999))


def test_query_service_get_task_intent(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service returns task intent by ID."""
    session_factory = sqlite_session_factory
    actor = _actor_context()

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session,
            TaskIntentInput(
                summary="Important task",
                details="Some details",
                origin_reference="signal:msg-1",
            ),
            actor,
        )
        session.commit()
        intent_id = intent.id

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.get_task_intent(TaskIntentGetRequest(task_intent_id=intent_id))

    assert result.task_intent.id == intent_id
    assert result.task_intent.summary == "Important task"
    assert result.task_intent.details == "Some details"


def test_query_service_list_schedules(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service lists schedules with filters."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        session.commit()

    service = ScheduleQueryServiceImpl(session_factory)
    all_result = service.list_schedules(ScheduleListRequest())
    one_time_result = service.list_schedules(
        ScheduleListRequest(schedule_type="one_time")
    )

    assert len(all_result.schedules) == 2
    assert len(one_time_result.schedules) == 1


def test_query_service_list_schedule_audits(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service lists schedule audit logs with filters."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 19, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1, interval_unit="day"
                ),
            ),
            actor,
            now=now,
        )
        pause_schedule(
            session,
            schedule.id,
            ActorContext(
                actor_type="human",
                actor_id="user-1",
                channel="signal",
                trace_id="trace-pause",
            ),
            now=now + timedelta(minutes=5),
        )
        session.commit()
        schedule_id = schedule.id

    service = ScheduleQueryServiceImpl(session_factory)
    all_result = service.list_schedule_audits(ScheduleAuditListRequest())
    filtered_result = service.list_schedule_audits(
        ScheduleAuditListRequest(schedule_id=schedule_id, event_type="pause")
    )

    assert len(all_result.audit_logs) == 2
    assert len(filtered_result.audit_logs) == 1
    assert filtered_result.audit_logs[0].event_type == "pause"


def test_query_service_list_execution_audits(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service lists execution audit logs."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    now = datetime(2025, 1, 20, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now),
            ),
            actor,
            now=now - timedelta(hours=1),
        )
        execution = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=now,
                status="queued",
            ),
            execution_actor,
        )
        session.commit()
        schedule_id = schedule.id
        execution_id = execution.id

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.list_execution_audits(
        ExecutionAuditListRequest(schedule_id=schedule_id)
    )

    assert len(result.audit_logs) == 1
    assert result.audit_logs[0].execution_id == execution_id
    assert result.audit_logs[0].status == "queued"


def test_query_service_get_schedule_audit(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service fetches schedule audit by ID."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 21, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=1)),
            ),
            actor,
            now=now,
        )
        session.commit()

        from models import ScheduleAuditLog

        audit = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule.id)
            .first()
        )
        audit_id = audit.id

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.get_schedule_audit(
        ScheduleAuditGetRequest(schedule_audit_id=audit_id)
    )

    assert result.audit_log.id == audit_id
    assert result.audit_log.event_type == "create"


def test_query_service_list_predicate_evaluation_audits(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service lists predicate evaluation audit logs."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 22, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        _create_predicate_evaluation_audit(
            session, schedule.id, intent.id, "eval-svc-001", now
        )
        _create_predicate_evaluation_audit(
            session, schedule.id, intent.id, "eval-svc-002", now + timedelta(hours=1)
        )
        session.commit()
        schedule_id = schedule.id

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.list_predicate_evaluation_audits(
        PredicateEvaluationAuditListRequest(schedule_id=schedule_id)
    )

    assert len(result.audit_logs) == 2


def test_query_service_get_predicate_evaluation_audit_by_evaluation_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service fetches predicate evaluation audit by evaluation_id."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 23, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Test task"), actor
        )
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="conditional",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    predicate_subject="skill.health",
                    predicate_operator="eq",
                    predicate_value="ok",
                    evaluation_interval_count=1,
                    evaluation_interval_unit="hour",
                ),
            ),
            actor,
            now=now,
        )
        _create_predicate_evaluation_audit(
            session, schedule.id, intent.id, "eval-unique-123", now
        )
        session.commit()

    service = ScheduleQueryServiceImpl(session_factory)
    result = service.get_predicate_evaluation_audit(
        PredicateEvaluationAuditGetRequest(evaluation_id="eval-unique-123")
    )

    assert result.audit_log.evaluation_id == "eval-unique-123"


def test_query_service_predicate_evaluation_audit_not_found(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure query service raises error for missing predicate evaluation audit."""
    session_factory = sqlite_session_factory
    service = ScheduleQueryServiceImpl(session_factory)

    with pytest.raises(ScheduleNotFoundError):
        service.get_predicate_evaluation_audit(
            PredicateEvaluationAuditGetRequest(evaluation_id="nonexistent")
        )


# ============================================================================
# Basic Performance Tests for Audit Log Queries
# ============================================================================


def test_schedule_audit_query_performance_with_many_records(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Verify schedule audit queries perform reasonably with larger datasets.

    This test creates a moderate number of audit records and verifies
    that filtered queries with pagination complete without timing out.
    The goal is to ensure indexes are effective and queries don't degrade
    significantly with scale.
    """
    import time

    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc)

    # Create a reasonable number of audit records for performance testing
    num_schedules = 20
    num_mutations_per_schedule = 5

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Performance test"), actor
        )
        for i in range(num_schedules):
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="interval",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        interval_count=1, interval_unit="day"
                    ),
                ),
                actor,
                now=now + timedelta(minutes=i),
            )
            # Add multiple mutations to generate more audit records
            for j in range(num_mutations_per_schedule):
                update_schedule(
                    session,
                    schedule.id,
                    ScheduleUpdateInput(timezone="America/New_York"),
                    ActorContext(
                        actor_type="human",
                        actor_id="user-perf",
                        channel="api",
                        trace_id=f"trace-perf-{i}-{j}",
                    ),
                    now=now + timedelta(minutes=i, seconds=j + 1),
                )
        session.commit()
        target_schedule_id = schedule.id

    # Time the query operations
    start_time = time.time()

    with closing(session_factory()) as session:
        # Query all audits with pagination
        page1 = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(limit=50)
        )

        # Query by specific schedule
        filtered = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(schedule_id=target_schedule_id)
        )

        # Query by event type
        creates = list_schedule_audits(
            session, ScheduleAuditHistoryQuery(event_type="create", limit=50)
        )

        # Query by time range
        time_filtered = list_schedule_audits(
            session,
            ScheduleAuditHistoryQuery(
                occurred_after=now,
                occurred_before=now + timedelta(hours=1),
                limit=50,
            ),
        )

    elapsed_time = time.time() - start_time

    # Verify results are correct
    total_expected = num_schedules * (num_mutations_per_schedule + 1)  # +1 for create
    assert page1.next_cursor is not None  # Should have more records
    assert len(filtered.audit_logs) == num_mutations_per_schedule + 1
    assert len(creates.audit_logs) == num_schedules
    assert len(time_filtered.audit_logs) > 0

    # Basic performance check - queries should complete in reasonable time
    # Allow generous time for CI environments
    assert elapsed_time < 5.0, f"Queries took {elapsed_time:.2f}s, expected < 5s"


def test_predicate_evaluation_audit_query_performance(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Verify predicate evaluation audit queries perform reasonably.

    Creates multiple predicate evaluation audit records and verifies
    that filtered queries with pagination complete efficiently.
    """
    import time

    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 2, 2, 10, 0, tzinfo=timezone.utc)

    num_schedules = 10
    num_evaluations_per_schedule = 10

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session, TaskIntentInput(summary="Perf test"), actor
        )
        schedules = []
        for i in range(num_schedules):
            schedule = create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="conditional",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        predicate_subject="skill.health",
                        predicate_operator="eq",
                        predicate_value="ok",
                        evaluation_interval_count=1,
                        evaluation_interval_unit="hour",
                    ),
                ),
                actor,
                now=now,
            )
            schedules.append(schedule)
            for j in range(num_evaluations_per_schedule):
                _create_predicate_evaluation_audit(
                    session,
                    schedule.id,
                    intent.id,
                    f"eval-perf-{i:03d}-{j:03d}",
                    now + timedelta(hours=i, minutes=j),
                    status="true" if j % 2 == 0 else "false",
                )
        session.commit()
        target_schedule_id = schedules[-1].id

    start_time = time.time()

    with closing(session_factory()) as session:
        # Query all audits
        page1 = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(limit=50)
        )

        # Query by schedule
        by_schedule = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(schedule_id=target_schedule_id),
        )

        # Query by status
        true_status = list_predicate_evaluation_audits(
            session, PredicateEvaluationAuditHistoryQuery(status="true", limit=50)
        )

        # Query by time range
        time_filtered = list_predicate_evaluation_audits(
            session,
            PredicateEvaluationAuditHistoryQuery(
                evaluated_after=now,
                evaluated_before=now + timedelta(hours=5),
                limit=50,
            ),
        )

    elapsed_time = time.time() - start_time

    # Verify results
    assert page1.next_cursor is not None
    assert len(by_schedule.audit_logs) == num_evaluations_per_schedule
    assert len(true_status.audit_logs) > 0
    assert len(time_filtered.audit_logs) > 0

    # Performance check
    assert elapsed_time < 5.0, f"Queries took {elapsed_time:.2f}s, expected < 5s"
