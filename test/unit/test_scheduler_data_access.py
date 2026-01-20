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
