"""Data access layer for scheduler task intents, schedules, executions, and audit logs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_
from sqlalchemy.orm import Session

from models import (
    BackoffStrategyEnum,
    Execution,
    ExecutionAuditLog,
    ExecutionStatusEnum,
    IntervalUnitEnum,
    PredicateOperatorEnum,
    Schedule,
    ScheduleAuditEventTypeEnum,
    ScheduleAuditLog,
    ScheduleStateEnum,
    ScheduleTypeEnum,
    TaskIntent,
)

logger = logging.getLogger(__name__)

UNSET = object()


@dataclass(frozen=True)
class ActorContext:
    """Actor context metadata for schedule mutations and audits."""

    actor_type: str
    actor_id: str | None
    channel: str
    trace_id: str
    request_id: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class TaskIntentInput:
    """Input payload for creating a task intent."""

    summary: str
    details: str | None = None
    origin_reference: str | None = None


@dataclass(frozen=True)
class ScheduleDefinitionInput:
    """Definition payload for schedule creation or replacement updates."""

    run_at: datetime | None = None
    interval_count: int | None = None
    interval_unit: str | None = None
    anchor_at: datetime | None = None
    rrule: str | None = None
    calendar_anchor_at: datetime | None = None
    predicate_subject: str | None = None
    predicate_operator: str | None = None
    predicate_value: str | None = None
    evaluation_interval_count: int | None = None
    evaluation_interval_unit: str | None = None


@dataclass(frozen=True)
class ScheduleCreateInput:
    """Input payload for creating a schedule."""

    task_intent_id: int
    schedule_type: str
    timezone: str
    definition: ScheduleDefinitionInput
    state: str = "active"
    next_run_at: datetime | None = None


@dataclass(frozen=True)
class ScheduleUpdateInput:
    """Input payload for updating a schedule."""

    timezone: str | object = UNSET
    state: str | object = UNSET
    next_run_at: datetime | None | object = UNSET
    last_run_at: datetime | None | object = UNSET
    last_run_status: str | None | object = UNSET
    failure_count: int | object = UNSET
    last_execution_id: int | None | object = UNSET
    last_evaluated_at: datetime | None | object = UNSET
    last_evaluation_status: str | None | object = UNSET
    last_evaluation_error_code: str | None | object = UNSET
    definition: ScheduleDefinitionInput | object = UNSET


@dataclass(frozen=True)
class ExecutionActorContext:
    """Actor context metadata for execution records and audits."""

    actor_type: str
    actor_id: str | None
    channel: str
    trace_id: str
    request_id: str | None = None
    actor_context: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class ExecutionCreateInput:
    """Input payload for creating an execution record."""

    task_intent_id: int
    schedule_id: int
    scheduled_for: datetime
    status: str = "queued"
    attempt_count: int = 0
    retry_count: int = 0
    max_attempts: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_count: int = 0
    retry_backoff_strategy: str | None = None
    next_retry_at: datetime | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None


@dataclass(frozen=True)
class ExecutionUpdateInput:
    """Input payload for updating execution records."""

    status: str | object = UNSET
    attempt_count: int | object = UNSET
    retry_count: int | object = UNSET
    max_attempts: int | object = UNSET
    started_at: datetime | None | object = UNSET
    finished_at: datetime | None | object = UNSET
    failure_count: int | object = UNSET
    retry_backoff_strategy: str | None | object = UNSET
    next_retry_at: datetime | None | object = UNSET
    last_error_code: str | None | object = UNSET
    last_error_message: str | None | object = UNSET


def _normalize_timestamp(value: datetime, label: str) -> datetime:
    """Ensure timestamps are timezone-aware, defaulting to UTC if naive."""
    if value.tzinfo is None:
        logger.warning("Naive timestamp provided for %s; assuming UTC.", label)
        return value.replace(tzinfo=timezone.utc)
    return value


def _validate_timezone(timezone_name: str) -> None:
    """Validate that the timezone name resolves to a ZoneInfo entry."""
    if not timezone_name.strip():
        raise ValueError("timezone is required.")
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone_name}") from exc


def _validate_actor_context(context: ActorContext, *, allow_scheduled: bool = False) -> None:
    """Validate actor context inputs for schedule mutations."""
    if not context.actor_type.strip():
        raise ValueError("actor_type is required.")
    if not context.channel.strip():
        raise ValueError("channel is required.")
    if not context.trace_id.strip():
        raise ValueError("trace_id is required.")
    if context.actor_type == "scheduled" and not allow_scheduled:
        raise ValueError("scheduled actor_type is not allowed for schedule mutations.")


def _validate_execution_actor_context(context: ExecutionActorContext) -> None:
    """Validate actor context inputs for execution records."""
    if not context.actor_type.strip():
        raise ValueError("actor_type is required.")
    if not context.channel.strip():
        raise ValueError("channel is required.")
    if not context.trace_id.strip():
        raise ValueError("trace_id is required.")


def _validate_schedule_type(schedule_type: str) -> None:
    """Validate schedule type against allowed values."""
    if schedule_type not in ScheduleTypeEnum.enums:
        raise ValueError(f"Invalid schedule_type: {schedule_type}.")


def _validate_schedule_state(state: str) -> None:
    """Validate schedule state against allowed values."""
    if state not in ScheduleStateEnum.enums:
        raise ValueError(f"Invalid schedule state: {state}.")


def _validate_execution_status(status: str) -> None:
    """Validate execution status against allowed values."""
    if status not in ExecutionStatusEnum.enums:
        raise ValueError(f"Invalid execution status: {status}.")


def _validate_interval_unit(unit: str | None) -> None:
    """Validate interval unit against allowed values."""
    if unit is None or unit not in IntervalUnitEnum.enums:
        raise ValueError("interval_unit is required and must be valid.")


def _validate_predicate_operator(operator: str | None) -> None:
    """Validate predicate operator against allowed values."""
    if operator is None or operator not in PredicateOperatorEnum.enums:
        raise ValueError("predicate_operator is required and must be valid.")


def _validate_definition(schedule_type: str, definition: ScheduleDefinitionInput) -> None:
    """Validate schedule definition fields based on schedule type."""
    _validate_schedule_type(schedule_type)

    if schedule_type == "one_time":
        if definition.run_at is None:
            raise ValueError("run_at is required for one_time schedules.")
    elif schedule_type == "interval":
        if definition.interval_count is None or definition.interval_count <= 0:
            raise ValueError("interval_count is required and must be > 0.")
        _validate_interval_unit(definition.interval_unit)
    elif schedule_type == "calendar_rule":
        if definition.rrule is None or not definition.rrule.strip():
            raise ValueError("rrule is required for calendar_rule schedules.")
    elif schedule_type == "conditional":
        if definition.predicate_subject is None or not definition.predicate_subject.strip():
            raise ValueError("predicate_subject is required for conditional schedules.")
        _validate_predicate_operator(definition.predicate_operator)
        if definition.predicate_operator != "exists":
            if definition.predicate_value is None or not str(definition.predicate_value).strip():
                raise ValueError("predicate_value is required for conditional schedules.")
        if (
            definition.evaluation_interval_count is None
            or definition.evaluation_interval_count <= 0
        ):
            raise ValueError("evaluation_interval_count is required and must be > 0.")
        if (
            definition.evaluation_interval_unit is None
            or definition.evaluation_interval_unit not in ("minute", "hour", "day", "week")
        ):
            raise ValueError("evaluation_interval_unit is required and must be valid.")


def _definition_fields(definition: ScheduleDefinitionInput) -> dict[str, object | None]:
    """Return a dictionary of schedule definition fields."""
    return {
        "run_at": definition.run_at,
        "interval_count": definition.interval_count,
        "interval_unit": definition.interval_unit,
        "anchor_at": definition.anchor_at,
        "rrule": definition.rrule,
        "calendar_anchor_at": definition.calendar_anchor_at,
        "predicate_subject": definition.predicate_subject,
        "predicate_operator": definition.predicate_operator,
        "predicate_value": definition.predicate_value,
        "evaluation_interval_count": definition.evaluation_interval_count,
        "evaluation_interval_unit": definition.evaluation_interval_unit,
    }


def _compute_diff_summary(
    changes: Iterable[str],
    extra: Iterable[str] | None = None,
) -> str | None:
    """Build a diff summary string from changed fields."""
    changed = list(changes)
    if extra:
        changed.extend(extra)
    if not changed:
        return None
    return ", ".join(sorted(set(changed)))


def create_task_intent(
    session: Session,
    intent_input: TaskIntentInput,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> TaskIntent:
    """Create a task intent with actor attribution."""
    _validate_actor_context(actor)
    if not intent_input.summary.strip():
        raise ValueError("summary is required.")
    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "created_at")

    intent = TaskIntent(
        summary=intent_input.summary.strip(),
        details=intent_input.details,
        creator_actor_type=actor.actor_type,
        creator_actor_id=actor.actor_id,
        creator_channel=actor.channel,
        origin_reference=intent_input.origin_reference,
        created_at=timestamp,
        updated_at=timestamp,
    )
    session.add(intent)
    session.flush()
    return intent


def get_task_intent(session: Session, intent_id: int) -> TaskIntent | None:
    """Fetch a task intent by id."""
    return session.query(TaskIntent).filter(TaskIntent.id == intent_id).first()


def update_task_intent(
    session: Session,
    intent_id: int,
    *,
    summary: str | None = None,
    details: str | None = None,
    origin_reference: str | None = None,
    superseded_by_intent_id: int | None = None,
    updated_at: datetime | None = None,
) -> TaskIntent:
    """Update a task intent only by superseding it."""
    intent = get_task_intent(session, intent_id)
    if intent is None:
        raise ValueError("task intent not found.")
    if summary is not None or details is not None or origin_reference is not None:
        raise ValueError("task intent is immutable; only superseding is allowed.")
    if superseded_by_intent_id is not None:
        if superseded_by_intent_id == intent.id:
            raise ValueError("task intent cannot supersede itself.")
        intent.superseded_by_intent_id = superseded_by_intent_id
    intent.updated_at = _normalize_timestamp(updated_at or datetime.now(timezone.utc), "updated_at")
    session.flush()
    return intent


def create_schedule(
    session: Session,
    schedule_input: ScheduleCreateInput,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Create a schedule and write an audit entry."""
    _validate_actor_context(actor)
    _validate_schedule_type(schedule_input.schedule_type)
    _validate_schedule_state(schedule_input.state)
    _validate_timezone(schedule_input.timezone)
    _validate_definition(schedule_input.schedule_type, schedule_input.definition)

    if get_task_intent(session, schedule_input.task_intent_id) is None:
        raise ValueError("task intent not found.")

    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "created_at")
    schedule = Schedule(
        task_intent_id=schedule_input.task_intent_id,
        schedule_type=schedule_input.schedule_type,
        state=schedule_input.state,
        timezone=schedule_input.timezone,
        next_run_at=schedule_input.next_run_at,
        created_by_actor_type=actor.actor_type,
        created_by_actor_id=actor.actor_id,
        created_at=timestamp,
        updated_at=timestamp,
        **_definition_fields(schedule_input.definition),
    )
    session.add(schedule)
    session.flush()
    _record_schedule_audit(
        session,
        schedule,
        actor,
        event_type="create",
        diff_summary=_compute_diff_summary(_definition_fields(schedule_input.definition).keys()),
        occurred_at=timestamp,
    )
    return schedule


def update_schedule(
    session: Session,
    schedule_id: int,
    updates: ScheduleUpdateInput,
    actor: ActorContext,
    *,
    event_type: str = "update",
    now: datetime | None = None,
) -> Schedule:
    """Update a schedule and write an audit entry."""
    _validate_actor_context(actor)
    if event_type not in ScheduleAuditEventTypeEnum.enums:
        raise ValueError(f"Invalid schedule audit event: {event_type}.")

    schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule is None:
        raise ValueError("schedule not found.")

    changes: list[str] = []
    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "updated_at")

    if updates.timezone is not UNSET:
        _validate_timezone(str(updates.timezone))
        schedule.timezone = str(updates.timezone)
        changes.append("timezone")
    if updates.state is not UNSET:
        _validate_schedule_state(str(updates.state))
        schedule.state = str(updates.state)
        changes.append("state")
    if updates.next_run_at is not UNSET:
        schedule.next_run_at = updates.next_run_at
        changes.append("next_run_at")
    if updates.last_run_at is not UNSET:
        schedule.last_run_at = updates.last_run_at
        changes.append("last_run_at")
    if updates.last_run_status is not UNSET:
        if updates.last_run_status is not None:
            _validate_execution_status(str(updates.last_run_status))
            schedule.last_run_status = str(updates.last_run_status)
        else:
            schedule.last_run_status = None
        changes.append("last_run_status")
    if updates.failure_count is not UNSET:
        schedule.failure_count = int(updates.failure_count)
        changes.append("failure_count")
    if updates.last_execution_id is not UNSET:
        schedule.last_execution_id = updates.last_execution_id
        changes.append("last_execution_id")
    if updates.last_evaluated_at is not UNSET:
        schedule.last_evaluated_at = updates.last_evaluated_at
        changes.append("last_evaluated_at")
    if updates.last_evaluation_status is not UNSET:
        schedule.last_evaluation_status = updates.last_evaluation_status
        changes.append("last_evaluation_status")
    if updates.last_evaluation_error_code is not UNSET:
        schedule.last_evaluation_error_code = updates.last_evaluation_error_code
        changes.append("last_evaluation_error_code")
    if updates.definition is not UNSET:
        definition = updates.definition
        if not isinstance(definition, ScheduleDefinitionInput):
            raise ValueError("definition must be provided as ScheduleDefinitionInput.")
        _validate_definition(schedule.schedule_type, definition)
        for field_name, value in _definition_fields(definition).items():
            setattr(schedule, field_name, value)
        changes.append("definition")

    schedule.updated_at = timestamp
    session.flush()
    _record_schedule_audit(
        session,
        schedule,
        actor,
        event_type=event_type,
        diff_summary=_compute_diff_summary(changes),
        occurred_at=timestamp,
    )
    return schedule


def pause_schedule(
    session: Session,
    schedule_id: int,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Pause a schedule and write an audit entry."""
    return update_schedule(
        session,
        schedule_id,
        ScheduleUpdateInput(state="paused"),
        actor,
        event_type="pause",
        now=now,
    )


def resume_schedule(
    session: Session,
    schedule_id: int,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Resume a schedule and write an audit entry."""
    return update_schedule(
        session,
        schedule_id,
        ScheduleUpdateInput(state="active"),
        actor,
        event_type="resume",
        now=now,
    )


def delete_schedule(
    session: Session,
    schedule_id: int,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Cancel a schedule and write an audit entry."""
    return update_schedule(
        session,
        schedule_id,
        ScheduleUpdateInput(state="canceled"),
        actor,
        event_type="delete",
        now=now,
    )


def list_active_schedules(session: Session) -> list[Schedule]:
    """Return active schedules."""
    return session.query(Schedule).filter(Schedule.state == "active").all()


def list_due_schedules(session: Session, now: datetime) -> list[Schedule]:
    """Return schedules due at or before the provided timestamp."""
    now = _normalize_timestamp(now, "now")
    return (
        session.query(Schedule)
        .filter(and_(Schedule.state == "active", Schedule.next_run_at <= now))
        .all()
    )


def list_execution_history(
    session: Session,
    schedule_id: int,
    limit: int = 100,
) -> list[Execution]:
    """Return execution history for a schedule."""
    return (
        session.query(Execution)
        .filter(Execution.schedule_id == schedule_id)
        .order_by(Execution.created_at.desc())
        .limit(limit)
        .all()
    )


def create_execution(
    session: Session,
    execution_input: ExecutionCreateInput,
    actor: ExecutionActorContext,
    *,
    now: datetime | None = None,
) -> Execution:
    """Create an execution record and write an audit entry."""
    _validate_execution_actor_context(actor)
    _validate_execution_status(execution_input.status)
    if execution_input.retry_backoff_strategy is not None:
        if execution_input.retry_backoff_strategy not in BackoffStrategyEnum.enums:
            raise ValueError("retry_backoff_strategy must be valid when provided.")

    if get_task_intent(session, execution_input.task_intent_id) is None:
        raise ValueError("task intent not found.")
    schedule = session.query(Schedule).filter(Schedule.id == execution_input.schedule_id).first()
    if schedule is None:
        raise ValueError("schedule not found.")

    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "created_at")
    scheduled_for = _normalize_timestamp(execution_input.scheduled_for, "scheduled_for")
    execution = Execution(
        task_intent_id=execution_input.task_intent_id,
        schedule_id=execution_input.schedule_id,
        scheduled_for=scheduled_for,
        created_at=timestamp,
        updated_at=timestamp,
        actor_type=actor.actor_type,
        actor_context=actor.actor_context,
        correlation_id=actor.correlation_id,
        status=execution_input.status,
        attempt_count=execution_input.attempt_count,
        retry_count=execution_input.retry_count,
        max_attempts=execution_input.max_attempts,
        started_at=execution_input.started_at,
        finished_at=execution_input.finished_at,
        failure_count=execution_input.failure_count,
        retry_backoff_strategy=execution_input.retry_backoff_strategy,
        next_retry_at=execution_input.next_retry_at,
        last_error_code=execution_input.last_error_code,
        last_error_message=execution_input.last_error_message,
    )
    session.add(execution)
    session.flush()
    _record_execution_audit(
        session,
        execution,
        actor,
        occurred_at=timestamp,
    )
    return execution


def update_execution(
    session: Session,
    execution_id: int,
    updates: ExecutionUpdateInput,
    actor: ExecutionActorContext,
    *,
    now: datetime | None = None,
) -> Execution:
    """Update an execution record and write an audit entry."""
    _validate_execution_actor_context(actor)

    execution = session.query(Execution).filter(Execution.id == execution_id).first()
    if execution is None:
        raise ValueError("execution not found.")

    if updates.status is not UNSET:
        if updates.status is not None:
            _validate_execution_status(str(updates.status))
            execution.status = str(updates.status)
        else:
            raise ValueError("status cannot be null.")
    if updates.attempt_count is not UNSET:
        execution.attempt_count = int(updates.attempt_count)
    if updates.retry_count is not UNSET:
        execution.retry_count = int(updates.retry_count)
    if updates.max_attempts is not UNSET:
        execution.max_attempts = int(updates.max_attempts)
    if updates.started_at is not UNSET:
        execution.started_at = updates.started_at
    if updates.finished_at is not UNSET:
        execution.finished_at = updates.finished_at
    if updates.failure_count is not UNSET:
        execution.failure_count = int(updates.failure_count)
    if updates.retry_backoff_strategy is not UNSET:
        if updates.retry_backoff_strategy is None:
            execution.retry_backoff_strategy = None
        else:
            if updates.retry_backoff_strategy not in BackoffStrategyEnum.enums:
                raise ValueError("retry_backoff_strategy must be valid when provided.")
            execution.retry_backoff_strategy = str(updates.retry_backoff_strategy)
    if updates.next_retry_at is not UNSET:
        execution.next_retry_at = updates.next_retry_at
    if updates.last_error_code is not UNSET:
        execution.last_error_code = updates.last_error_code
    if updates.last_error_message is not UNSET:
        execution.last_error_message = updates.last_error_message

    execution.updated_at = _normalize_timestamp(now or datetime.now(timezone.utc), "updated_at")
    session.flush()
    _record_execution_audit(
        session,
        execution,
        actor,
        occurred_at=execution.updated_at,
    )
    return execution


def _record_schedule_audit(
    session: Session,
    schedule: Schedule,
    actor: ActorContext,
    *,
    event_type: str,
    diff_summary: str | None,
    occurred_at: datetime,
) -> ScheduleAuditLog:
    """Persist a schedule audit log entry."""
    audit = ScheduleAuditLog(
        schedule_id=schedule.id,
        task_intent_id=schedule.task_intent_id,
        event_type=event_type,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_channel=actor.channel,
        trace_id=actor.trace_id,
        request_id=actor.request_id,
        reason=actor.reason,
        diff_summary=diff_summary,
        occurred_at=occurred_at,
    )
    session.add(audit)
    session.flush()
    return audit


def _record_execution_audit(
    session: Session,
    execution: Execution,
    actor: ExecutionActorContext,
    *,
    occurred_at: datetime,
) -> ExecutionAuditLog:
    """Persist an execution audit log entry."""
    audit = ExecutionAuditLog(
        execution_id=execution.id,
        schedule_id=execution.schedule_id,
        task_intent_id=execution.task_intent_id,
        status=execution.status,
        scheduled_for=execution.scheduled_for,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        attempt_count=execution.attempt_count,
        retry_count=execution.retry_count,
        max_attempts=execution.max_attempts,
        failure_count=execution.failure_count,
        next_retry_at=execution.next_retry_at,
        last_error_code=execution.last_error_code,
        last_error_message=execution.last_error_message,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_channel=actor.channel,
        actor_context=actor.actor_context,
        trace_id=actor.trace_id,
        request_id=actor.request_id,
        correlation_id=actor.correlation_id,
        occurred_at=occurred_at,
    )
    session.add(audit)
    session.flush()
    return audit
