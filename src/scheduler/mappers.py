"""Shared model->view mappers for scheduler services."""

from __future__ import annotations

from models import Schedule, TaskIntent
from scheduler.schedule_service_interface import (
    ScheduleConflictError,
    ScheduleDefinitionView,
    ScheduleView,
    TaskIntentView,
)


def to_task_intent_view(intent: TaskIntent) -> TaskIntentView:
    """Convert a TaskIntent model into its view equivalent."""
    return TaskIntentView(
        id=intent.id,
        summary=intent.summary,
        details=intent.details,
        origin_reference=intent.origin_reference,
        creator_actor_type=intent.creator_actor_type,
        creator_actor_id=intent.creator_actor_id,
        creator_channel=intent.creator_channel,
        created_at=intent.created_at,
        superseded_by_intent_id=intent.superseded_by_intent_id,
    )


def to_schedule_definition_view(schedule: Schedule) -> ScheduleDefinitionView:
    """Convert schedule definition metadata into a view payload."""
    return ScheduleDefinitionView(
        run_at=schedule.run_at,
        interval_count=schedule.interval_count,
        interval_unit=schedule.interval_unit,
        anchor_at=schedule.anchor_at,
        rrule=schedule.rrule,
        calendar_anchor_at=schedule.calendar_anchor_at,
        predicate_subject=schedule.predicate_subject,
        predicate_operator=schedule.predicate_operator,
        predicate_value=schedule.predicate_value,
        evaluation_interval_count=schedule.evaluation_interval_count,
        evaluation_interval_unit=schedule.evaluation_interval_unit,
    )


def to_schedule_view(schedule: Schedule) -> ScheduleView:
    """Convert a Schedule model to its read-only ScheduleView, enforcing timezone safety."""
    timezone_value = _ensure_timezone(schedule)
    return ScheduleView(
        id=schedule.id,
        task_intent_id=schedule.task_intent_id,
        schedule_type=str(schedule.schedule_type),
        state=str(schedule.state),
        timezone=timezone_value,
        definition=to_schedule_definition_view(schedule),
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        last_run_status=str(schedule.last_run_status) if schedule.last_run_status else None,
        failure_count=int(schedule.failure_count or 0),
        created_at=schedule.created_at,
        created_by_actor_type=schedule.created_by_actor_type,
        created_by_actor_id=schedule.created_by_actor_id,
        updated_at=schedule.updated_at,
        last_execution_id=schedule.last_execution_id,
        last_evaluated_at=schedule.last_evaluated_at,
        last_evaluation_status=schedule.last_evaluation_status,
        last_evaluation_error_code=schedule.last_evaluation_error_code,
    )


def _ensure_timezone(schedule: Schedule) -> str:
    """Return the schedule timezone or raise a conflict error when missing."""
    timezone_value = schedule.timezone
    if timezone_value is None:
        raise ScheduleConflictError(
            "schedule timezone missing.",
            {"schedule_id": schedule.id},
        )
    return timezone_value
