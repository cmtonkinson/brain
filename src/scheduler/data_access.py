"""Data access layer for scheduler task intents, schedules, executions, and audit logs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from sqlalchemy import and_
from sqlalchemy.orm import Session

from models import (
    BackoffStrategyEnum,
    Execution,
    ExecutionAuditLog,
    ExecutionStatusEnum,
    PredicateEvaluationAuditLog,
    Schedule,
    ScheduleAuditEventTypeEnum,
    ScheduleAuditLog,
    TaskIntent,
)
from scheduler.schedule_validation import (
    validate_schedule_definition,
    validate_schedule_state,
    validate_schedule_state_transition,
    validate_schedule_type,
    validate_task_intent_immutable,
    validate_timezone,
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
class ScheduleCreateWithIntentInput:
    """Input payload for creating a schedule with inline task intent."""

    task_intent: TaskIntentInput
    schedule_type: str
    timezone: str
    definition: ScheduleDefinitionInput
    state: str = "active"
    next_run_at: datetime | None = None


@dataclass(frozen=True)
class ScheduleUpdateInput:
    """Input payload for updating a schedule."""

    task_intent_id: int | object = UNSET
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


def _validate_execution_status(status: str) -> None:
    """Validate execution status against allowed values."""
    if status not in ExecutionStatusEnum.enums:
        raise ValueError(f"Invalid execution status: {status}.")


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


def create_schedule_with_intent(
    session: Session,
    schedule_input: ScheduleCreateWithIntentInput,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> tuple[TaskIntent, Schedule]:
    """Create a task intent and schedule from an inline intent payload."""
    if schedule_input.task_intent is None:
        raise ValueError("task intent is required.")
    if not isinstance(schedule_input.task_intent, TaskIntentInput):
        raise ValueError("task intent must be provided as TaskIntentInput.")
    if not isinstance(schedule_input.definition, ScheduleDefinitionInput):
        raise ValueError("definition must be provided as ScheduleDefinitionInput.")

    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "created_at")
    validate_schedule_type(schedule_input.schedule_type)
    validate_schedule_state(schedule_input.state)
    validate_timezone(schedule_input.timezone)
    validate_schedule_definition(
        schedule_input.schedule_type,
        schedule_input.definition,
        now=timestamp,
        require_future_run_at=True,
    )
    intent = create_task_intent(session, schedule_input.task_intent, actor, now=timestamp)
    schedule = create_schedule(
        session,
        ScheduleCreateInput(
            task_intent_id=intent.id,
            schedule_type=schedule_input.schedule_type,
            timezone=schedule_input.timezone,
            definition=schedule_input.definition,
            state=schedule_input.state,
            next_run_at=schedule_input.next_run_at,
        ),
        actor,
        now=timestamp,
    )
    return intent, schedule


def create_schedule(
    session: Session,
    schedule_input: ScheduleCreateInput,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> Schedule:
    """Create a schedule and write an audit entry."""
    _validate_actor_context(actor)
    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "created_at")
    validate_schedule_type(schedule_input.schedule_type)
    validate_schedule_state(schedule_input.state)
    validate_timezone(schedule_input.timezone)
    validate_schedule_definition(
        schedule_input.schedule_type,
        schedule_input.definition,
        now=timestamp,
        require_future_run_at=True,
    )

    if get_task_intent(session, schedule_input.task_intent_id) is None:
        raise ValueError("task intent not found.")

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

    if updates.task_intent_id is not UNSET:
        validate_task_intent_immutable(schedule.task_intent_id, updates.task_intent_id)
    if updates.timezone is not UNSET:
        validate_timezone(str(updates.timezone))
        schedule.timezone = str(updates.timezone)
        changes.append("timezone")
    if updates.state is not UNSET:
        target_state = str(updates.state)
        validate_schedule_state(target_state)
        allow_noop = event_type not in {"pause", "resume", "delete"}
        validate_schedule_state_transition(
            schedule.state,
            target_state,
            allow_noop=allow_noop,
        )
        schedule.state = target_state
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
        validate_schedule_definition(
            schedule.schedule_type,
            definition,
            now=timestamp,
            require_future_run_at=True,
        )
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


def record_schedule_audit(
    session: Session,
    schedule_id: int,
    actor: ActorContext,
    *,
    event_type: str,
    diff_summary: str | None = None,
    now: datetime | None = None,
) -> ScheduleAuditLog:
    """Record a schedule audit entry without mutating the schedule."""
    _validate_actor_context(actor)
    if event_type not in ScheduleAuditEventTypeEnum.enums:
        raise ValueError(f"Invalid schedule audit event: {event_type}.")
    schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule is None:
        raise ValueError("schedule not found.")
    timestamp = _normalize_timestamp(now or datetime.now(timezone.utc), "occurred_at")
    return _record_schedule_audit(
        session,
        schedule,
        actor,
        event_type=event_type,
        diff_summary=diff_summary,
        occurred_at=timestamp,
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


def get_execution_by_trace_id(
    session: Session,
    schedule_id: int,
    trace_id: str,
) -> Execution | None:
    """Return the latest execution matching a schedule and trace id."""
    if not trace_id.strip():
        raise ValueError("trace_id is required.")
    return (
        session.query(Execution)
        .filter(
            Execution.schedule_id == schedule_id,
            Execution.trace_id == trace_id,
        )
        .order_by(Execution.id.desc())
        .first()
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
        trace_id=actor.trace_id,
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
    if actor.request_id:
        existing = (
            session.query(ScheduleAuditLog)
            .filter(
                ScheduleAuditLog.schedule_id == schedule.id,
                ScheduleAuditLog.event_type == event_type,
                ScheduleAuditLog.request_id == actor.request_id,
            )
            .order_by(ScheduleAuditLog.id.desc())
            .first()
        )
        if existing is not None:
            return existing
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
    if actor.request_id:
        existing = (
            session.query(ExecutionAuditLog)
            .filter(
                ExecutionAuditLog.execution_id == execution.id,
                ExecutionAuditLog.status == execution.status,
                ExecutionAuditLog.request_id == actor.request_id,
            )
            .order_by(ExecutionAuditLog.id.desc())
            .first()
        )
        if existing is not None:
            return existing
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
        occurred_at=occurred_at,
    )
    session.add(audit)
    session.flush()
    return audit


@dataclass(frozen=True)
class PredicateEvaluationAuditInput:
    """Input payload for predicate evaluation audit records."""

    evaluation_id: str
    schedule_id: int
    execution_id: int | None
    task_intent_id: int
    actor_type: str
    actor_id: str | None
    actor_channel: str
    actor_privilege_level: str
    actor_autonomy_level: str
    trace_id: str
    request_id: str | None
    predicate_subject: str
    predicate_operator: str
    predicate_value: str | None
    predicate_value_type: str
    evaluation_time: datetime
    evaluated_at: datetime
    status: str
    result_code: str
    message: str | None
    observed_value: str | None
    error_code: str | None
    error_message: str | None
    authorization_decision: str
    authorization_reason_code: str | None
    authorization_reason_message: str | None
    authorization_policy_name: str | None
    authorization_policy_version: str | None
    provider_name: str
    provider_attempt: int
    correlation_id: str


def record_predicate_evaluation_audit(
    session: Session,
    audit_input: PredicateEvaluationAuditInput,
) -> PredicateEvaluationAuditLog:
    """Persist a predicate evaluation audit log entry with idempotency.

    If an audit record with the same evaluation_id already exists, returns
    the existing record instead of creating a duplicate.

    Args:
        session: SQLAlchemy session.
        audit_input: Audit input payload.

    Returns:
        The created or existing PredicateEvaluationAuditLog.
    """
    # Idempotency check: evaluation_id is unique
    existing = (
        session.query(PredicateEvaluationAuditLog)
        .filter(PredicateEvaluationAuditLog.evaluation_id == audit_input.evaluation_id)
        .first()
    )
    if existing is not None:
        return existing

    audit = PredicateEvaluationAuditLog(
        evaluation_id=audit_input.evaluation_id,
        schedule_id=audit_input.schedule_id,
        execution_id=audit_input.execution_id,
        task_intent_id=audit_input.task_intent_id,
        actor_type=audit_input.actor_type,
        actor_id=audit_input.actor_id,
        actor_channel=audit_input.actor_channel,
        actor_privilege_level=audit_input.actor_privilege_level,
        actor_autonomy_level=audit_input.actor_autonomy_level,
        trace_id=audit_input.trace_id,
        request_id=audit_input.request_id,
        predicate_subject=audit_input.predicate_subject,
        predicate_operator=audit_input.predicate_operator,
        predicate_value=audit_input.predicate_value,
        predicate_value_type=audit_input.predicate_value_type,
        evaluation_time=audit_input.evaluation_time,
        evaluated_at=audit_input.evaluated_at,
        status=audit_input.status,
        result_code=audit_input.result_code,
        message=audit_input.message,
        observed_value=audit_input.observed_value,
        error_code=audit_input.error_code,
        error_message=audit_input.error_message,
        authorization_decision=audit_input.authorization_decision,
        authorization_reason_code=audit_input.authorization_reason_code,
        authorization_reason_message=audit_input.authorization_reason_message,
        authorization_policy_name=audit_input.authorization_policy_name,
        authorization_policy_version=audit_input.authorization_policy_version,
        provider_name=audit_input.provider_name,
        provider_attempt=audit_input.provider_attempt,
        correlation_id=audit_input.correlation_id,
    )
    session.add(audit)
    session.flush()
    return audit


def get_predicate_evaluation_audit_by_evaluation_id(
    session: Session,
    evaluation_id: str,
) -> PredicateEvaluationAuditLog | None:
    """Fetch a predicate evaluation audit log by evaluation_id.

    Args:
        session: SQLAlchemy session.
        evaluation_id: The unique evaluation identifier.

    Returns:
        The PredicateEvaluationAuditLog or None if not found.
    """
    return (
        session.query(PredicateEvaluationAuditLog)
        .filter(PredicateEvaluationAuditLog.evaluation_id == evaluation_id)
        .first()
    )


def list_predicate_evaluation_audits_by_schedule(
    session: Session,
    schedule_id: int,
    limit: int = 100,
) -> list[PredicateEvaluationAuditLog]:
    """Return predicate evaluation audit logs for a schedule.

    Args:
        session: SQLAlchemy session.
        schedule_id: The schedule ID to filter by.
        limit: Maximum number of records to return.

    Returns:
        List of PredicateEvaluationAuditLog ordered by evaluated_at desc.
    """
    return (
        session.query(PredicateEvaluationAuditLog)
        .filter(PredicateEvaluationAuditLog.schedule_id == schedule_id)
        .order_by(PredicateEvaluationAuditLog.evaluated_at.desc())
        .limit(limit)
        .all()
    )


@dataclass(frozen=True)
class ExecutionHistoryQuery:
    """Query parameters for execution history with filtering and pagination.

    Supports filtering by schedule_id, task_intent_id, status, time range,
    and actor_type. Results are ordered by created_at descending by default.
    Pagination is implemented using cursor-based navigation.
    """

    schedule_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    actor_type: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True)
class ExecutionHistoryResult:
    """Result of execution history query with pagination support.

    Contains the list of executions and the next cursor for pagination.
    If next_cursor is None, there are no more results.
    """

    executions: list[Execution]
    next_cursor: int | None
    total_count: int | None = None


def get_execution(session: Session, execution_id: int) -> Execution | None:
    """Fetch an execution record by ID.

    Args:
        session: SQLAlchemy session.
        execution_id: The execution ID to fetch.

    Returns:
        The Execution record or None if not found.
    """
    return session.query(Execution).filter(Execution.id == execution_id).first()


def list_executions(
    session: Session,
    query: ExecutionHistoryQuery,
) -> ExecutionHistoryResult:
    """List executions with filtering, ordering, and pagination.

    Supports filtering by schedule_id, task_intent_id, status, actor_type,
    and time range. Results are ordered by created_at descending.
    Uses cursor-based pagination for efficient traversal.

    Args:
        session: SQLAlchemy session.
        query: Query parameters including filters, limit, and cursor.

    Returns:
        ExecutionHistoryResult containing matching executions and pagination cursor.

    Raises:
        ValueError: If status filter is invalid.
    """
    if query.status is not None:
        _validate_execution_status(query.status)

    filters = []

    if query.schedule_id is not None:
        filters.append(Execution.schedule_id == query.schedule_id)
    if query.task_intent_id is not None:
        filters.append(Execution.task_intent_id == query.task_intent_id)
    if query.status is not None:
        filters.append(Execution.status == query.status)
    if query.actor_type is not None:
        filters.append(Execution.actor_type == query.actor_type)
    if query.created_after is not None:
        created_after = _normalize_timestamp(query.created_after, "created_after")
        filters.append(Execution.created_at >= created_after)
    if query.created_before is not None:
        created_before = _normalize_timestamp(query.created_before, "created_before")
        filters.append(Execution.created_at <= created_before)
    if query.cursor is not None:
        filters.append(Execution.id < query.cursor)

    base_query = session.query(Execution)
    if filters:
        base_query = base_query.filter(and_(*filters))

    # Fetch one extra to determine if there are more results
    fetch_limit = query.limit + 1
    executions = (
        base_query
        .order_by(Execution.id.desc())
        .limit(fetch_limit)
        .all()
    )

    has_more = len(executions) > query.limit
    if has_more:
        executions = executions[:query.limit]
        next_cursor = executions[-1].id if executions else None
    else:
        next_cursor = None

    return ExecutionHistoryResult(
        executions=executions,
        next_cursor=next_cursor,
    )


@dataclass(frozen=True)
class ExecutionAuditHistoryQuery:
    """Query parameters for execution audit history with filtering and pagination.

    Supports filtering by execution_id, schedule_id, task_intent_id, status,
    and time range. Results are ordered by occurred_at descending by default.
    """

    execution_id: int | None = None
    schedule_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True)
class ExecutionAuditHistoryResult:
    """Result of execution audit history query with pagination support.

    Contains the list of audit logs and the next cursor for pagination.
    """

    audit_logs: list[ExecutionAuditLog]
    next_cursor: int | None


def get_execution_audit(session: Session, audit_id: int) -> ExecutionAuditLog | None:
    """Fetch an execution audit log by ID.

    Args:
        session: SQLAlchemy session.
        audit_id: The execution audit log ID to fetch.

    Returns:
        The ExecutionAuditLog record or None if not found.
    """
    return (
        session.query(ExecutionAuditLog)
        .filter(ExecutionAuditLog.id == audit_id)
        .first()
    )


def list_execution_audits(
    session: Session,
    query: ExecutionAuditHistoryQuery,
) -> ExecutionAuditHistoryResult:
    """List execution audit logs with filtering, ordering, and pagination.

    Supports filtering by execution_id, schedule_id, task_intent_id, status,
    and time range. Results are ordered by occurred_at descending.
    Uses cursor-based pagination for efficient traversal.

    Args:
        session: SQLAlchemy session.
        query: Query parameters including filters, limit, and cursor.

    Returns:
        ExecutionAuditHistoryResult containing matching audit logs and pagination cursor.

    Raises:
        ValueError: If status filter is invalid.
    """
    if query.status is not None:
        _validate_execution_status(query.status)

    filters = []

    if query.execution_id is not None:
        filters.append(ExecutionAuditLog.execution_id == query.execution_id)
    if query.schedule_id is not None:
        filters.append(ExecutionAuditLog.schedule_id == query.schedule_id)
    if query.task_intent_id is not None:
        filters.append(ExecutionAuditLog.task_intent_id == query.task_intent_id)
    if query.status is not None:
        filters.append(ExecutionAuditLog.status == query.status)
    if query.occurred_after is not None:
        occurred_after = _normalize_timestamp(query.occurred_after, "occurred_after")
        filters.append(ExecutionAuditLog.occurred_at >= occurred_after)
    if query.occurred_before is not None:
        occurred_before = _normalize_timestamp(query.occurred_before, "occurred_before")
        filters.append(ExecutionAuditLog.occurred_at <= occurred_before)
    if query.cursor is not None:
        filters.append(ExecutionAuditLog.id < query.cursor)

    base_query = session.query(ExecutionAuditLog)
    if filters:
        base_query = base_query.filter(and_(*filters))

    # Fetch one extra to determine if there are more results
    fetch_limit = query.limit + 1
    audit_logs = (
        base_query
        .order_by(ExecutionAuditLog.id.desc())
        .limit(fetch_limit)
        .all()
    )

    has_more = len(audit_logs) > query.limit
    if has_more:
        audit_logs = audit_logs[:query.limit]
        next_cursor = audit_logs[-1].id if audit_logs else None
    else:
        next_cursor = None

    return ExecutionAuditHistoryResult(
        audit_logs=audit_logs,
        next_cursor=next_cursor,
    )


# ============================================================================
# Schedule Audit History Querying
# ============================================================================


def _validate_schedule_audit_event_type(event_type: str) -> None:
    """Validate schedule audit event type against allowed values."""
    if event_type not in ScheduleAuditEventTypeEnum.enums:
        raise ValueError(f"Invalid schedule audit event type: {event_type}.")


@dataclass(frozen=True)
class ScheduleAuditHistoryQuery:
    """Query parameters for schedule audit history with filtering and pagination.

    Supports filtering by schedule_id, task_intent_id, event_type, and time range.
    Results are ordered by id descending by default.
    """

    schedule_id: int | None = None
    task_intent_id: int | None = None
    event_type: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True)
class ScheduleAuditHistoryResult:
    """Result of schedule audit history query with pagination support.

    Contains the list of audit logs and the next cursor for pagination.
    """

    audit_logs: list[ScheduleAuditLog]
    next_cursor: int | None


def get_schedule_audit(session: Session, audit_id: int) -> ScheduleAuditLog | None:
    """Fetch a schedule audit log by ID.

    Args:
        session: SQLAlchemy session.
        audit_id: The schedule audit log ID to fetch.

    Returns:
        The ScheduleAuditLog record or None if not found.
    """
    return (
        session.query(ScheduleAuditLog)
        .filter(ScheduleAuditLog.id == audit_id)
        .first()
    )


def list_schedule_audits(
    session: Session,
    query: ScheduleAuditHistoryQuery,
) -> ScheduleAuditHistoryResult:
    """List schedule audit logs with filtering, ordering, and pagination.

    Supports filtering by schedule_id, task_intent_id, event_type, and time range.
    Results are ordered by id descending.
    Uses cursor-based pagination for efficient traversal.

    Args:
        session: SQLAlchemy session.
        query: Query parameters including filters, limit, and cursor.

    Returns:
        ScheduleAuditHistoryResult containing matching audit logs and pagination cursor.

    Raises:
        ValueError: If event_type filter is invalid.
    """
    if query.event_type is not None:
        _validate_schedule_audit_event_type(query.event_type)

    filters = []

    if query.schedule_id is not None:
        filters.append(ScheduleAuditLog.schedule_id == query.schedule_id)
    if query.task_intent_id is not None:
        filters.append(ScheduleAuditLog.task_intent_id == query.task_intent_id)
    if query.event_type is not None:
        filters.append(ScheduleAuditLog.event_type == query.event_type)
    if query.occurred_after is not None:
        occurred_after = _normalize_timestamp(query.occurred_after, "occurred_after")
        filters.append(ScheduleAuditLog.occurred_at >= occurred_after)
    if query.occurred_before is not None:
        occurred_before = _normalize_timestamp(query.occurred_before, "occurred_before")
        filters.append(ScheduleAuditLog.occurred_at <= occurred_before)
    if query.cursor is not None:
        filters.append(ScheduleAuditLog.id < query.cursor)

    base_query = session.query(ScheduleAuditLog)
    if filters:
        base_query = base_query.filter(and_(*filters))

    # Fetch one extra to determine if there are more results
    fetch_limit = query.limit + 1
    audit_logs = (
        base_query
        .order_by(ScheduleAuditLog.id.desc())
        .limit(fetch_limit)
        .all()
    )

    has_more = len(audit_logs) > query.limit
    if has_more:
        audit_logs = audit_logs[:query.limit]
        next_cursor = audit_logs[-1].id if audit_logs else None
    else:
        next_cursor = None

    return ScheduleAuditHistoryResult(
        audit_logs=audit_logs,
        next_cursor=next_cursor,
    )


# ============================================================================
# Predicate Evaluation Audit History Querying
# ============================================================================


def _validate_predicate_evaluation_status(status: str) -> None:
    """Validate predicate evaluation status against allowed values."""
    from models import PredicateEvaluationStatusEnum

    if status not in PredicateEvaluationStatusEnum.enums:
        raise ValueError(f"Invalid predicate evaluation status: {status}.")


@dataclass(frozen=True)
class PredicateEvaluationAuditHistoryQuery:
    """Query parameters for predicate evaluation audit history with filtering and pagination.

    Supports filtering by schedule_id, execution_id, task_intent_id, status,
    and time range. Results are ordered by id descending by default.
    """

    schedule_id: int | None = None
    execution_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    evaluated_after: datetime | None = None
    evaluated_before: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True)
class PredicateEvaluationAuditHistoryResult:
    """Result of predicate evaluation audit history query with pagination support.

    Contains the list of audit logs and the next cursor for pagination.
    """

    audit_logs: list[PredicateEvaluationAuditLog]
    next_cursor: int | None


def get_predicate_evaluation_audit(
    session: Session,
    audit_id: int,
) -> PredicateEvaluationAuditLog | None:
    """Fetch a predicate evaluation audit log by ID.

    Args:
        session: SQLAlchemy session.
        audit_id: The predicate evaluation audit log ID to fetch.

    Returns:
        The PredicateEvaluationAuditLog record or None if not found.
    """
    return (
        session.query(PredicateEvaluationAuditLog)
        .filter(PredicateEvaluationAuditLog.id == audit_id)
        .first()
    )


def list_predicate_evaluation_audits(
    session: Session,
    query: PredicateEvaluationAuditHistoryQuery,
) -> PredicateEvaluationAuditHistoryResult:
    """List predicate evaluation audit logs with filtering, ordering, and pagination.

    Supports filtering by schedule_id, execution_id, task_intent_id, status,
    and time range. Results are ordered by id descending.
    Uses cursor-based pagination for efficient traversal.

    Args:
        session: SQLAlchemy session.
        query: Query parameters including filters, limit, and cursor.

    Returns:
        PredicateEvaluationAuditHistoryResult containing matching audit logs and cursor.

    Raises:
        ValueError: If status filter is invalid.
    """
    if query.status is not None:
        _validate_predicate_evaluation_status(query.status)

    filters = []

    if query.schedule_id is not None:
        filters.append(PredicateEvaluationAuditLog.schedule_id == query.schedule_id)
    if query.execution_id is not None:
        filters.append(PredicateEvaluationAuditLog.execution_id == query.execution_id)
    if query.task_intent_id is not None:
        filters.append(PredicateEvaluationAuditLog.task_intent_id == query.task_intent_id)
    if query.status is not None:
        filters.append(PredicateEvaluationAuditLog.status == query.status)
    if query.evaluated_after is not None:
        evaluated_after = _normalize_timestamp(query.evaluated_after, "evaluated_after")
        filters.append(PredicateEvaluationAuditLog.evaluated_at >= evaluated_after)
    if query.evaluated_before is not None:
        evaluated_before = _normalize_timestamp(query.evaluated_before, "evaluated_before")
        filters.append(PredicateEvaluationAuditLog.evaluated_at <= evaluated_before)
    if query.cursor is not None:
        filters.append(PredicateEvaluationAuditLog.id < query.cursor)

    base_query = session.query(PredicateEvaluationAuditLog)
    if filters:
        base_query = base_query.filter(and_(*filters))

    # Fetch one extra to determine if there are more results
    fetch_limit = query.limit + 1
    audit_logs = (
        base_query
        .order_by(PredicateEvaluationAuditLog.id.desc())
        .limit(fetch_limit)
        .all()
    )

    has_more = len(audit_logs) > query.limit
    if has_more:
        audit_logs = audit_logs[:query.limit]
        next_cursor = audit_logs[-1].id if audit_logs else None
    else:
        next_cursor = None

    return PredicateEvaluationAuditHistoryResult(
        audit_logs=audit_logs,
        next_cursor=next_cursor,
    )


# ============================================================================
# Schedule and Task Intent Querying
# ============================================================================


def get_schedule(session: Session, schedule_id: int) -> Schedule | None:
    """Fetch a schedule by ID.

    Args:
        session: SQLAlchemy session.
        schedule_id: The schedule ID to fetch.

    Returns:
        The Schedule record or None if not found.
    """
    return session.query(Schedule).filter(Schedule.id == schedule_id).first()


@dataclass(frozen=True)
class ScheduleListQuery:
    """Query parameters for schedule listing with filtering and pagination.

    Supports filtering by state, schedule_type, created_by_actor_type, and time range.
    Results are ordered by id descending by default.
    """

    state: str | None = None
    schedule_type: str | None = None
    created_by_actor_type: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True)
class ScheduleListResult:
    """Result of schedule listing query with pagination support.

    Contains the list of schedules and the next cursor for pagination.
    """

    schedules: list[Schedule]
    next_cursor: int | None


def list_schedules(
    session: Session,
    query: ScheduleListQuery,
) -> ScheduleListResult:
    """List schedules with filtering, ordering, and pagination.

    Supports filtering by state, schedule_type, created_by_actor_type, and time range.
    Results are ordered by id descending.
    Uses cursor-based pagination for efficient traversal.

    Args:
        session: SQLAlchemy session.
        query: Query parameters including filters, limit, and cursor.

    Returns:
        ScheduleListResult containing matching schedules and pagination cursor.

    Raises:
        ValueError: If state or schedule_type filter is invalid.
    """
    if query.state is not None:
        validate_schedule_state(query.state)
    if query.schedule_type is not None:
        validate_schedule_type(query.schedule_type)

    filters = []

    if query.state is not None:
        filters.append(Schedule.state == query.state)
    if query.schedule_type is not None:
        filters.append(Schedule.schedule_type == query.schedule_type)
    if query.created_by_actor_type is not None:
        filters.append(Schedule.created_by_actor_type == query.created_by_actor_type)
    if query.created_after is not None:
        created_after = _normalize_timestamp(query.created_after, "created_after")
        filters.append(Schedule.created_at >= created_after)
    if query.created_before is not None:
        created_before = _normalize_timestamp(query.created_before, "created_before")
        filters.append(Schedule.created_at <= created_before)
    if query.cursor is not None:
        filters.append(Schedule.id < query.cursor)

    base_query = session.query(Schedule)
    if filters:
        base_query = base_query.filter(and_(*filters))

    # Fetch one extra to determine if there are more results
    fetch_limit = query.limit + 1
    schedules = (
        base_query
        .order_by(Schedule.id.desc())
        .limit(fetch_limit)
        .all()
    )

    has_more = len(schedules) > query.limit
    if has_more:
        schedules = schedules[:query.limit]
        next_cursor = schedules[-1].id if schedules else None
    else:
        next_cursor = None

    return ScheduleListResult(
        schedules=schedules,
        next_cursor=next_cursor,
    )
