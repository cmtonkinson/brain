"""Unit tests for scheduler data access layer."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from models import ExecutionAuditLog, ScheduleAuditLog
from scheduler.data_access import (
    ActorContext,
    ExecutionActorContext,
    ExecutionCreateInput,
    ExecutionUpdateInput,
    ScheduleCreateWithIntentInput,
    ScheduleCreateInput,
    ScheduleDefinitionInput,
    ScheduleUpdateInput,
    TaskIntentInput,
    create_execution,
    create_schedule,
    create_schedule_with_intent,
    create_task_intent,
    list_due_schedules,
    pause_schedule,
    delete_schedule,
    resume_schedule,
    update_execution,
    update_schedule,
    update_task_intent,
)
from scheduler.schedule_service_interface import ScheduleValidationError


def _actor_context() -> ActorContext:
    """Return a default actor context for schedule mutations."""
    return ActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="signal",
        trace_id="trace-123",
        request_id="req-456",
        reason="testing",
    )


def _execution_actor_context() -> ExecutionActorContext:
    """Return a default actor context for execution records."""
    return ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-789",
        request_id="req-999",
        actor_context="scheduled-envelope",
    )


def test_task_intent_creation_populates_audit_fields(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure task intent creation persists actor and timestamp fields."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session,
            TaskIntentInput(
                summary="  Check status  ",
                details="Details",
                origin_reference="signal:msg-1",
            ),
            actor,
            now=now,
        )
        session.commit()
        session.refresh(intent)

        assert intent.summary == "Check status"
        assert intent.details == "Details"
        assert intent.origin_reference == "signal:msg-1"
        assert intent.creator_actor_type == actor.actor_type
        assert intent.creator_actor_id == actor.actor_id
        assert intent.creator_channel == actor.channel
        assert intent.created_at == now.replace(tzinfo=None)
        assert intent.updated_at == now.replace(tzinfo=None)


def test_schedule_create_with_intent_requires_payload(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure inline schedule creation requires a task intent payload."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    run_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        with pytest.raises(ValueError):
            create_schedule_with_intent(
                session,
                ScheduleCreateWithIntentInput(
                    task_intent=None,
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=run_at),
                ),
                actor,
            )


def test_schedule_create_with_intent_rejects_blank_summary(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure inline intent creation rejects blank summaries."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    run_at = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    validation_now = run_at - timedelta(hours=1)

    with closing(session_factory()) as session:
        with pytest.raises(ValueError):
            create_schedule_with_intent(
                session,
                ScheduleCreateWithIntentInput(
                    task_intent=TaskIntentInput(summary="   "),
                    schedule_type="one_time",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(run_at=run_at),
                ),
                actor,
                now=validation_now,
            )


def test_task_intent_immutability_enforced(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure task intents cannot be mutated beyond superseding."""
    session_factory = sqlite_session_factory
    actor = _actor_context()

    with closing(session_factory()) as session:
        intent = create_task_intent(
            session,
            TaskIntentInput(summary="Remind me", details="Details"),
            actor,
        )
        replacement = create_task_intent(
            session,
            TaskIntentInput(summary="Updated reminder"),
            actor,
        )

        with pytest.raises(ValueError):
            update_task_intent(session, intent.id, summary="Changed")

        updated = update_task_intent(
            session,
            intent.id,
            superseded_by_intent_id=replacement.id,
        )
        session.flush()

        assert updated.superseded_by_intent_id == replacement.id
        session.commit()


def test_schedule_create_writes_audit_and_due_query(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure schedule creation writes audits and due query returns active schedules."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Daily brief"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(
                    interval_count=1,
                    interval_unit="day",
                ),
                next_run_at=now - timedelta(minutes=5),
            ),
            actor,
            now=now,
        )
        session.commit()

        audits = session.query(ScheduleAuditLog).filter_by(schedule_id=schedule.id).all()
        due = list_due_schedules(session, now)

    assert schedule.id is not None
    assert len(audits) == 1
    assert audits[0].event_type == "create"
    assert audits[0].actor_type == actor.actor_type
    assert audits[0].actor_id == actor.actor_id
    assert audits[0].actor_channel == actor.channel
    assert audits[0].trace_id == actor.trace_id
    assert audits[0].request_id == actor.request_id
    assert audits[0].reason == actor.reason
    assert schedule.id in {entry.id for entry in due}


def test_schedule_definition_validation_rejects_missing_cadence(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure conditional schedules require evaluation cadence and predicate value."""
    session_factory = sqlite_session_factory
    actor = _actor_context()

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Check status"), actor)
        with pytest.raises(ScheduleValidationError):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="conditional",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        predicate_subject="skill.health",
                        predicate_operator="eq",
                        predicate_value="ok",
                    ),
                ),
                actor,
            )

        with pytest.raises(ScheduleValidationError):
            create_schedule(
                session,
                ScheduleCreateInput(
                    task_intent_id=intent.id,
                    schedule_type="conditional",
                    timezone="UTC",
                    definition=ScheduleDefinitionInput(
                        predicate_subject="skill.health",
                        predicate_operator="eq",
                        evaluation_interval_count=1,
                        evaluation_interval_unit="hour",
                    ),
                ),
                actor,
            )


def test_schedule_update_writes_audit(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure schedule updates write audit entries."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="One time"), actor)
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
        update_schedule(
            session,
            schedule.id,
            ScheduleUpdateInput(
                definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=2)),
            ),
            actor,
            now=now,
        )
        session.commit()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert [audit.event_type for audit in audits] == ["create", "update"]


def test_schedule_state_mutations_write_audit_entries(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure pause/resume/delete mutations emit audit records."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Lifecycle"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=now,
        )
        pause_schedule(session, schedule.id, actor, now=now)
        resume_schedule(session, schedule.id, actor, now=now)
        delete_schedule(session, schedule.id, actor, now=now)
        session.commit()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert [audit.event_type for audit in audits] == [
        "create",
        "pause",
        "resume",
        "delete",
    ]


def test_schedule_audit_idempotent_by_request_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure repeated updates with the same request id avoid duplicate audits."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    now = datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Idempotent"), actor)
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
        update_payload = ScheduleUpdateInput(
            definition=ScheduleDefinitionInput(run_at=now + timedelta(hours=2)),
        )
        update_schedule(session, schedule.id, update_payload, actor, now=now)
        update_schedule(session, schedule.id, update_payload, actor, now=now)
        session.commit()
        audits = (
            session.query(ScheduleAuditLog)
            .filter_by(schedule_id=schedule.id)
            .order_by(ScheduleAuditLog.id.asc())
            .all()
        )

    assert [audit.event_type for audit in audits] == ["create", "update"]


def test_execution_audit_logging_on_create_and_update(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure execution creation and updates write audit records."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 3, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Run task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        execution = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
                max_attempts=2,
            ),
            execution_actor,
        )
        update_execution(
            session,
            execution.id,
            ExecutionUpdateInput(
                status="failed",
                failure_count=1,
                last_error_code="timeout",
                last_error_message="Task timed out.",
                finished_at=scheduled_for + timedelta(minutes=5),
            ),
            execution_actor,
        )
        session.commit()
        audits = (
            session.query(ExecutionAuditLog)
            .filter_by(execution_id=execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )

    assert [audit.status for audit in audits] == ["queued", "failed"]


def test_execution_audit_idempotent_by_request_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure repeated execution updates with the same request id avoid duplicate audits."""
    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-123",
        request_id="req-dup",
        actor_context="scheduled-envelope",
    )
    scheduled_for = datetime(2025, 1, 4, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Run task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        execution = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
                max_attempts=2,
            ),
            execution_actor,
        )
        update_execution(
            session,
            execution.id,
            ExecutionUpdateInput(
                status="failed",
                failure_count=1,
                last_error_code="timeout",
                last_error_message="Task timed out.",
                finished_at=scheduled_for + timedelta(minutes=5),
            ),
            execution_actor,
        )
        update_execution(
            session,
            execution.id,
            ExecutionUpdateInput(
                status="failed",
                failure_count=1,
                last_error_code="timeout",
                last_error_message="Task timed out.",
                finished_at=scheduled_for + timedelta(minutes=5),
            ),
            execution_actor,
        )
        session.commit()
        audits = (
            session.query(ExecutionAuditLog)
            .filter_by(execution_id=execution.id)
            .order_by(ExecutionAuditLog.id.asc())
            .all()
        )

    assert [audit.status for audit in audits] == ["queued", "failed"]


# ============================================================================
# Execution History Querying Tests (Task 24)
# ============================================================================


def test_get_execution_returns_record_by_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure get_execution returns the execution by ID."""
    from scheduler.data_access import get_execution

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 5, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        execution = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
            ),
            execution_actor,
        )
        session.commit()

        # Store IDs before session closes
        execution_id = execution.id
        schedule_id = schedule.id

        result = get_execution(session, execution_id)
        not_found = get_execution(session, 99999)

        assert result is not None
        assert result.id == execution_id
        assert result.schedule_id == schedule_id
        assert result.status == "queued"
        assert not_found is None


def test_list_executions_no_filters_returns_all(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions returns all executions when no filters are applied."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        for i in range(3):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for + timedelta(days=i),
                    status="succeeded",
                ),
                execution_actor,
            )
        session.commit()

        result = list_executions(session, ExecutionHistoryQuery())

    assert len(result.executions) == 3
    # Ordered by id desc (most recent first)
    assert result.executions[0].id > result.executions[1].id
    assert result.next_cursor is None


def test_list_executions_filter_by_schedule_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions filters by schedule_id."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 7, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule1 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        schedule2 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for + timedelta(hours=1)),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        # Two executions for schedule1
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule1.id,
                scheduled_for=scheduled_for,
                status="succeeded",
            ),
            execution_actor,
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule1.id,
                scheduled_for=scheduled_for + timedelta(minutes=5),
                status="failed",
            ),
            execution_actor,
        )
        # One execution for schedule2
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule2.id,
                scheduled_for=scheduled_for + timedelta(hours=1),
                status="succeeded",
            ),
            execution_actor,
        )
        session.commit()

        result1 = list_executions(session, ExecutionHistoryQuery(schedule_id=schedule1.id))
        result2 = list_executions(session, ExecutionHistoryQuery(schedule_id=schedule2.id))

    assert len(result1.executions) == 2
    assert all(e.schedule_id == schedule1.id for e in result1.executions)
    assert len(result2.executions) == 1
    assert result2.executions[0].schedule_id == schedule2.id


def test_list_executions_filter_by_status(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions filters by status."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 8, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        for status in ["succeeded", "succeeded", "failed", "queued"]:
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for,
                    status=status,
                ),
                execution_actor,
            )
        session.commit()

        succeeded = list_executions(session, ExecutionHistoryQuery(status="succeeded"))
        failed = list_executions(session, ExecutionHistoryQuery(status="failed"))
        queued = list_executions(session, ExecutionHistoryQuery(status="queued"))

    assert len(succeeded.executions) == 2
    assert all(e.status == "succeeded" for e in succeeded.executions)
    assert len(failed.executions) == 1
    assert failed.executions[0].status == "failed"
    assert len(queued.executions) == 1


def test_list_executions_filter_by_actor_type(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions filters by actor_type."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    scheduled_for = datetime(2025, 1, 9, 10, 0, tzinfo=timezone.utc)

    scheduled_actor = ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduled",
        trace_id="trace-sched",
    )
    human_actor = ExecutionActorContext(
        actor_type="human",
        actor_id="user-1",
        channel="api",
        trace_id="trace-human",
    )

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        # Two scheduled executions
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="succeeded",
            ),
            scheduled_actor,
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for + timedelta(days=1),
                status="succeeded",
            ),
            scheduled_actor,
        )
        # One human-triggered execution
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for + timedelta(days=2),
                status="succeeded",
            ),
            human_actor,
        )
        session.commit()

        scheduled_result = list_executions(session, ExecutionHistoryQuery(actor_type="scheduled"))
        human_result = list_executions(session, ExecutionHistoryQuery(actor_type="human"))

    assert len(scheduled_result.executions) == 2
    assert all(e.actor_type == "scheduled" for e in scheduled_result.executions)
    assert len(human_result.executions) == 1
    assert human_result.executions[0].actor_type == "human"


def test_list_executions_filter_by_time_range(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions filters by created_after and created_before."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    base_time = datetime(2025, 1, 10, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=base_time - timedelta(hours=1),
        )
        # Create executions at different times
        times = [
            base_time,
            base_time + timedelta(hours=1),
            base_time + timedelta(hours=2),
            base_time + timedelta(hours=3),
        ]
        for t in times:
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=t,
                    status="succeeded",
                ),
                execution_actor,
                now=t,
            )
        session.commit()

        # Filter: created after 1 hour mark
        after_result = list_executions(
            session,
            ExecutionHistoryQuery(created_after=base_time + timedelta(hours=1)),
        )
        # Filter: created before 2 hour mark
        before_result = list_executions(
            session,
            ExecutionHistoryQuery(created_before=base_time + timedelta(hours=2)),
        )
        # Filter: within a time window
        window_result = list_executions(
            session,
            ExecutionHistoryQuery(
                created_after=base_time + timedelta(hours=1),
                created_before=base_time + timedelta(hours=2),
            ),
        )

    assert len(after_result.executions) == 3  # hours 1, 2, 3
    assert len(before_result.executions) == 3  # hours 0, 1, 2
    assert len(window_result.executions) == 2  # hours 1, 2


def test_list_executions_pagination_with_cursor(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions pagination works with cursor."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 11, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        # Create 5 executions
        for i in range(5):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for + timedelta(days=i),
                    status="succeeded",
                ),
                execution_actor,
            )
        session.commit()

        # First page: limit 2
        page1 = list_executions(session, ExecutionHistoryQuery(limit=2))
        assert len(page1.executions) == 2
        assert page1.next_cursor is not None

        # Second page: use cursor
        page2 = list_executions(session, ExecutionHistoryQuery(limit=2, cursor=page1.next_cursor))
        assert len(page2.executions) == 2
        assert page2.next_cursor is not None
        # Verify no overlap
        page1_ids = {e.id for e in page1.executions}
        page2_ids = {e.id for e in page2.executions}
        assert page1_ids.isdisjoint(page2_ids)

        # Third page: should have 1 record and no next cursor
        page3 = list_executions(session, ExecutionHistoryQuery(limit=2, cursor=page2.next_cursor))
        assert len(page3.executions) == 1
        assert page3.next_cursor is None


def test_list_executions_combined_filters(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions supports combining multiple filters."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    base_time = datetime(2025, 1, 12, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=base_time - timedelta(hours=1),
        )
        # Create varied executions
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=base_time,
                status="succeeded",
            ),
            execution_actor,
            now=base_time,
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=base_time + timedelta(hours=1),
                status="failed",
            ),
            execution_actor,
            now=base_time + timedelta(hours=1),
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=base_time + timedelta(hours=2),
                status="succeeded",
            ),
            execution_actor,
            now=base_time + timedelta(hours=2),
        )
        session.commit()

        # Combined: schedule_id + status + time range
        result = list_executions(
            session,
            ExecutionHistoryQuery(
                schedule_id=schedule.id,
                status="succeeded",
                created_after=base_time,
                created_before=base_time + timedelta(hours=3),
            ),
        )

    assert len(result.executions) == 2
    assert all(e.status == "succeeded" for e in result.executions)
    assert all(e.schedule_id == schedule.id for e in result.executions)


def test_list_executions_invalid_status_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions raises ValueError for invalid status."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory

    with closing(session_factory()) as session:
        with pytest.raises(ValueError, match="Invalid execution status"):
            list_executions(session, ExecutionHistoryQuery(status="invalid_status"))


def test_list_executions_order_by_id_desc(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_executions returns results ordered by id descending."""
    from scheduler.data_access import ExecutionHistoryQuery, list_executions

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 13, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        for i in range(3):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for + timedelta(days=i),
                    status="succeeded",
                ),
                execution_actor,
            )
        session.commit()

        result = list_executions(session, ExecutionHistoryQuery())

    ids = [e.id for e in result.executions]
    assert ids == sorted(ids, reverse=True)


# ============================================================================
# Execution Audit History Querying Tests
# ============================================================================


def test_get_execution_audit_returns_record_by_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure get_execution_audit returns the audit record by ID."""
    from scheduler.data_access import get_execution_audit

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 14, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        execution = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
            ),
            execution_actor,
        )
        session.commit()

        audits = session.query(ExecutionAuditLog).filter_by(execution_id=execution.id).all()
        audit_id = audits[0].id

        result = get_execution_audit(session, audit_id)
        not_found = get_execution_audit(session, 99999)

    assert result is not None
    assert result.id == audit_id
    assert result.execution_id == execution.id
    assert not_found is None


def test_list_execution_audits_filter_by_execution_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits filters by execution_id."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        exec1 = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
            ),
            execution_actor,
        )
        # Update to create multiple audit records
        update_execution(
            session,
            exec1.id,
            ExecutionUpdateInput(status="running"),
            ExecutionActorContext(
                actor_type="scheduled",
                actor_id=None,
                channel="scheduled",
                trace_id="trace-2",
            ),
        )
        update_execution(
            session,
            exec1.id,
            ExecutionUpdateInput(status="succeeded"),
            ExecutionActorContext(
                actor_type="scheduled",
                actor_id=None,
                channel="scheduled",
                trace_id="trace-3",
            ),
        )
        # Create a second execution
        exec2 = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for + timedelta(hours=1),
                status="queued",
            ),
            execution_actor,
        )
        session.commit()

        result1 = list_execution_audits(session, ExecutionAuditHistoryQuery(execution_id=exec1.id))
        result2 = list_execution_audits(session, ExecutionAuditHistoryQuery(execution_id=exec2.id))

    assert len(result1.audit_logs) == 3  # queued, running, succeeded
    assert all(a.execution_id == exec1.id for a in result1.audit_logs)
    assert len(result2.audit_logs) == 1  # just queued


def test_list_execution_audits_filter_by_schedule_id(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits filters by schedule_id."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 16, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        sched1 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        sched2 = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for + timedelta(hours=1)),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=sched1.id,
                scheduled_for=scheduled_for,
                status="succeeded",
            ),
            execution_actor,
        )
        create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=sched2.id,
                scheduled_for=scheduled_for + timedelta(hours=1),
                status="succeeded",
            ),
            execution_actor,
        )
        session.commit()

        result1 = list_execution_audits(session, ExecutionAuditHistoryQuery(schedule_id=sched1.id))
        result2 = list_execution_audits(session, ExecutionAuditHistoryQuery(schedule_id=sched2.id))

    assert len(result1.audit_logs) == 1
    assert result1.audit_logs[0].schedule_id == sched1.id
    assert len(result2.audit_logs) == 1
    assert result2.audit_logs[0].schedule_id == sched2.id


def test_list_execution_audits_filter_by_status(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits filters by status."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 17, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="one_time",
                timezone="UTC",
                definition=ScheduleDefinitionInput(run_at=scheduled_for),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        exec1 = create_execution(
            session,
            ExecutionCreateInput(
                task_intent_id=intent.id,
                schedule_id=schedule.id,
                scheduled_for=scheduled_for,
                status="queued",
            ),
            execution_actor,
        )
        update_execution(
            session,
            exec1.id,
            ExecutionUpdateInput(status="succeeded"),
            ExecutionActorContext(
                actor_type="scheduled",
                actor_id=None,
                channel="scheduled",
                trace_id="trace-success",
            ),
        )
        session.commit()

        queued_result = list_execution_audits(session, ExecutionAuditHistoryQuery(status="queued"))
        succeeded_result = list_execution_audits(
            session, ExecutionAuditHistoryQuery(status="succeeded")
        )

    assert len(queued_result.audit_logs) == 1
    assert queued_result.audit_logs[0].status == "queued"
    assert len(succeeded_result.audit_logs) == 1
    assert succeeded_result.audit_logs[0].status == "succeeded"


def test_list_execution_audits_filter_by_time_range(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits filters by occurred_after and occurred_before."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    base_time = datetime(2025, 1, 18, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=base_time - timedelta(hours=1),
        )
        # Create executions at different times
        for i in range(3):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=base_time + timedelta(hours=i),
                    status="succeeded",
                ),
                execution_actor,
                now=base_time + timedelta(hours=i),
            )
        session.commit()

        after_result = list_execution_audits(
            session,
            ExecutionAuditHistoryQuery(occurred_after=base_time + timedelta(hours=1)),
        )
        before_result = list_execution_audits(
            session,
            ExecutionAuditHistoryQuery(occurred_before=base_time + timedelta(hours=1)),
        )

    assert len(after_result.audit_logs) == 2  # hours 1 and 2
    assert len(before_result.audit_logs) == 2  # hours 0 and 1


def test_list_execution_audits_pagination_with_cursor(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits pagination works with cursor."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 19, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        # Create 5 executions (5 audit logs)
        for i in range(5):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for + timedelta(days=i),
                    status="succeeded",
                ),
                execution_actor,
            )
        session.commit()

        # First page
        page1 = list_execution_audits(session, ExecutionAuditHistoryQuery(limit=2))
        assert len(page1.audit_logs) == 2
        assert page1.next_cursor is not None

        # Second page
        page2 = list_execution_audits(
            session,
            ExecutionAuditHistoryQuery(limit=2, cursor=page1.next_cursor),
        )
        assert len(page2.audit_logs) == 2
        assert page2.next_cursor is not None

        # Third page - should have 1 record
        page3 = list_execution_audits(
            session,
            ExecutionAuditHistoryQuery(limit=2, cursor=page2.next_cursor),
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


def test_list_execution_audits_invalid_status_raises(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits raises ValueError for invalid status."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory

    with closing(session_factory()) as session:
        with pytest.raises(ValueError, match="Invalid execution status"):
            list_execution_audits(session, ExecutionAuditHistoryQuery(status="bad_status"))


def test_list_execution_audits_order_by_id_desc(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure list_execution_audits returns results ordered by id descending."""
    from scheduler.data_access import (
        ExecutionAuditHistoryQuery,
        list_execution_audits,
    )

    session_factory = sqlite_session_factory
    actor = _actor_context()
    execution_actor = _execution_actor_context()
    scheduled_for = datetime(2025, 1, 20, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        intent = create_task_intent(session, TaskIntentInput(summary="Test task"), actor)
        schedule = create_schedule(
            session,
            ScheduleCreateInput(
                task_intent_id=intent.id,
                schedule_type="interval",
                timezone="UTC",
                definition=ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
            ),
            actor,
            now=scheduled_for - timedelta(hours=1),
        )
        for i in range(3):
            create_execution(
                session,
                ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for + timedelta(days=i),
                    status="succeeded",
                ),
                execution_actor,
            )
        session.commit()

        result = list_execution_audits(session, ExecutionAuditHistoryQuery())

    ids = [a.id for a in result.audit_logs]
    assert ids == sorted(ids, reverse=True)
