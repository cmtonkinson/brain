"""Schedule command handlers for schedule management operations."""

from __future__ import annotations

from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, TypeVar

from sqlalchemy.orm import Session

from models import Execution, Schedule, ScheduleAuditLog, TaskIntent
from scheduler import data_access
from scheduler.actor_context import ScheduledActorContext
from scheduler.schedule_service_interface import (
    ActorContext,
    ExecutionRunNowResult,
    ExecutionView,
    ScheduleActorContextError,
    ScheduleConflictError,
    ScheduleCreateRequest,
    ScheduleDeleteRequest,
    ScheduleDeleteResult,
    ScheduleForbiddenError,
    ScheduleMutationResult,
    ScheduleNotFoundError,
    SchedulePauseRequest,
    ScheduleResumeRequest,
    ScheduleRunNowRequest,
    ScheduleServiceError,
    ScheduleUpdateRequest,
    ScheduleValidationError,
    ScheduleDefinitionView,
    ScheduleView,
    ScheduleDefinitionInput,
    TaskIntentView,
    TaskIntentInput,
)

ResultT = TypeVar("ResultT")


class ScheduleCommandServiceImpl:
    """Schedule command service backed by the scheduler data access layer."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the command service with a session factory."""
        self._session_factory = session_factory
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def create_schedule(
        self,
        request: ScheduleCreateRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Create a schedule and task intent from an inline request."""

        def handler(session: Session) -> ScheduleMutationResult:
            timestamp = self._now_provider()
            intent, schedule = data_access.create_schedule_with_intent(
                session,
                data_access.ScheduleCreateWithIntentInput(
                    task_intent=_to_task_intent_input(request.task_intent),
                    schedule_type=request.schedule_type,
                    timezone=request.timezone,
                    definition=_to_definition_input(request.definition),
                    state=request.start_state,
                ),
                _to_data_access_actor(actor),
                now=timestamp,
            )
            audit_log_id = _fetch_latest_schedule_audit_id(session, schedule.id, "create")
            return ScheduleMutationResult(
                schedule=_to_schedule_view(schedule),
                task_intent=_to_task_intent_view(intent),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def update_schedule(
        self,
        request: ScheduleUpdateRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Update mutable schedule fields."""

        def handler(session: Session) -> ScheduleMutationResult:
            timestamp = self._now_provider()
            schedule = data_access.update_schedule(
                session,
                request.schedule_id,
                _to_schedule_update_input(request),
                _to_data_access_actor(actor),
                event_type="update",
                now=timestamp,
            )
            task_intent = _fetch_task_intent(session, schedule.task_intent_id)
            audit_log_id = _fetch_latest_schedule_audit_id(session, schedule.id, "update")
            return ScheduleMutationResult(
                schedule=_to_schedule_view(schedule),
                task_intent=_to_task_intent_view(task_intent),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def pause_schedule(
        self,
        request: SchedulePauseRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Pause a schedule."""

        def handler(session: Session) -> ScheduleMutationResult:
            timestamp = self._now_provider()
            schedule = data_access.pause_schedule(
                session,
                request.schedule_id,
                _to_data_access_actor(_override_reason(actor, request.reason)),
                now=timestamp,
            )
            task_intent = _fetch_task_intent(session, schedule.task_intent_id)
            audit_log_id = _fetch_latest_schedule_audit_id(session, schedule.id, "pause")
            return ScheduleMutationResult(
                schedule=_to_schedule_view(schedule),
                task_intent=_to_task_intent_view(task_intent),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def resume_schedule(
        self,
        request: ScheduleResumeRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Resume a schedule."""

        def handler(session: Session) -> ScheduleMutationResult:
            timestamp = self._now_provider()
            schedule = data_access.resume_schedule(
                session,
                request.schedule_id,
                _to_data_access_actor(_override_reason(actor, request.reason)),
                now=timestamp,
            )
            task_intent = _fetch_task_intent(session, schedule.task_intent_id)
            audit_log_id = _fetch_latest_schedule_audit_id(session, schedule.id, "resume")
            return ScheduleMutationResult(
                schedule=_to_schedule_view(schedule),
                task_intent=_to_task_intent_view(task_intent),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def delete_schedule(
        self,
        request: ScheduleDeleteRequest,
        actor: ActorContext,
    ) -> ScheduleDeleteResult:
        """Delete (cancel) a schedule."""

        def handler(session: Session) -> ScheduleDeleteResult:
            timestamp = self._now_provider()
            schedule = data_access.delete_schedule(
                session,
                request.schedule_id,
                _to_data_access_actor(_override_reason(actor, request.reason)),
                now=timestamp,
            )
            audit_log_id = _fetch_latest_schedule_audit_id(session, schedule.id, "delete")
            return ScheduleDeleteResult(
                schedule_id=schedule.id,
                state=str(schedule.state),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def run_now(
        self,
        request: ScheduleRunNowRequest,
        actor: ActorContext,
    ) -> ExecutionRunNowResult:
        """Trigger a schedule execution immediately."""

        def handler(session: Session) -> ExecutionRunNowResult:
            timestamp = self._now_provider()
            schedule = _fetch_schedule(session, request.schedule_id)
            if str(schedule.state) not in {"active", "paused"}:
                raise ScheduleConflictError(
                    "run_now is only allowed for active or paused schedules.",
                    {"schedule_id": schedule.id, "state": str(schedule.state)},
                )
            requested_for = request.requested_for or timestamp
            execution = data_access.create_execution(
                session,
                data_access.ExecutionCreateInput(
                    task_intent_id=schedule.task_intent_id,
                    schedule_id=schedule.id,
                    scheduled_for=requested_for,
                    status="queued",
                ),
                _to_execution_actor_context(actor),
                now=timestamp,
            )
            audit_log_id = data_access.record_schedule_audit(
                session,
                schedule.id,
                _to_data_access_actor(_override_reason(actor, request.reason)),
                event_type="run_now",
                diff_summary="run_now",
                now=timestamp,
            ).id
            return ExecutionRunNowResult(
                execution=_to_execution_view(execution),
                audit_log_id=audit_log_id,
            )

        return self._execute(handler)

    def _execute(self, handler: Callable[[Session], ResultT]) -> ResultT:
        """Run a handler inside a managed session with error mapping."""
        with closing(self._session_factory()) as session:
            try:
                result = handler(session)
                session.commit()
                return result
            except Exception as exc:
                session.rollback()
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise _map_exception(exc) from exc


def _override_reason(actor: ActorContext, reason: str | None) -> ActorContext:
    """Return a copy of the actor context with the reason overridden."""
    if reason is None:
        return actor
    return ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        channel=actor.channel,
        trace_id=actor.trace_id,
        request_id=actor.request_id,
        reason=reason,
    )


def _to_data_access_actor(actor: ActorContext) -> data_access.ActorContext:
    """Map schedule interface actor context to data access actor context."""
    return data_access.ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        channel=actor.channel,
        trace_id=actor.trace_id,
        request_id=actor.request_id,
        reason=actor.reason,
    )


def _to_execution_actor_context(actor: ActorContext) -> data_access.ExecutionActorContext:
    """Map run-now actor context into a scheduled execution actor context."""
    scheduled_context = ScheduledActorContext()
    correlation_id = actor.request_id or actor.trace_id
    return data_access.ExecutionActorContext(
        actor_type=scheduled_context.actor_type,
        actor_id=None,
        channel=scheduled_context.channel,
        trace_id=actor.trace_id,
        request_id=actor.request_id,
        actor_context=scheduled_context.to_reference(
            trigger_source="run_now",
            requested_by=_format_requested_by(actor),
        ),
        correlation_id=correlation_id,
    )


def _format_requested_by(actor: ActorContext) -> str | None:
    """Return a compact requested-by label for scheduled actor context."""
    if not actor.actor_type:
        return None
    label = actor.actor_type.strip()
    if actor.channel:
        label = f"{label}@{actor.channel.strip()}"
    return label or None


def _to_task_intent_input(
    task_intent: TaskIntentInput,
) -> data_access.TaskIntentInput:
    """Map task intent input to data access payload."""
    payload = asdict(task_intent)
    return data_access.TaskIntentInput(**payload)


def _to_definition_input(
    definition: ScheduleDefinitionInput,
) -> data_access.ScheduleDefinitionInput:
    """Map schedule definition input to data access payload."""
    payload = asdict(definition)
    return data_access.ScheduleDefinitionInput(**payload)


def _to_schedule_update_input(
    request: ScheduleUpdateRequest,
) -> data_access.ScheduleUpdateInput:
    """Map schedule update request to data access update input."""
    definition: data_access.ScheduleDefinitionInput | object = data_access.UNSET
    if request.definition is not None:
        definition = _to_definition_input(request.definition)
    timezone = request.timezone if request.timezone is not None else data_access.UNSET
    state = request.state if request.state is not None else data_access.UNSET
    return data_access.ScheduleUpdateInput(
        timezone=timezone,
        state=state,
        definition=definition,
    )


def _fetch_schedule(session: Session, schedule_id: int) -> Schedule:
    """Fetch a schedule or raise a not-found error."""
    schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule is None:
        raise ScheduleNotFoundError(
            "schedule not found.",
            {"schedule_id": schedule_id},
        )
    return schedule


def _fetch_task_intent(session: Session, task_intent_id: int) -> TaskIntent:
    """Fetch a task intent or raise a not-found error."""
    intent = session.query(TaskIntent).filter(TaskIntent.id == task_intent_id).first()
    if intent is None:
        raise ScheduleNotFoundError(
            "task intent not found.",
            {"task_intent_id": task_intent_id},
        )
    return intent


def _fetch_latest_schedule_audit_id(
    session: Session,
    schedule_id: int,
    event_type: str,
) -> int:
    """Return the latest schedule audit log id for the event type."""
    audit = (
        session.query(ScheduleAuditLog)
        .filter(
            ScheduleAuditLog.schedule_id == schedule_id,
            ScheduleAuditLog.event_type == event_type,
        )
        .order_by(ScheduleAuditLog.id.desc())
        .first()
    )
    if audit is None:
        raise ScheduleConflictError(
            "schedule audit log missing.",
            {"schedule_id": schedule_id, "event_type": event_type},
        )
    return int(audit.id)


def _to_task_intent_view(intent: TaskIntent) -> TaskIntentView:
    """Map task intent model to view."""
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


def _to_schedule_definition_view(schedule: Schedule) -> ScheduleDefinitionView:
    """Map schedule definition fields into a view."""
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


def _to_schedule_view(schedule: Schedule) -> ScheduleView:
    """Map schedule model to view."""
    timezone_value = schedule.timezone
    if timezone_value is None:
        raise ScheduleConflictError(
            "schedule timezone missing.",
            {"schedule_id": schedule.id},
        )
    return ScheduleView(
        id=schedule.id,
        task_intent_id=schedule.task_intent_id,
        schedule_type=str(schedule.schedule_type),
        state=str(schedule.state),
        timezone=timezone_value,
        definition=_to_schedule_definition_view(schedule),
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


def _to_execution_view(execution: Execution) -> ExecutionView:
    """Map execution model to view."""
    return ExecutionView(
        id=execution.id,
        schedule_id=execution.schedule_id,
        task_intent_id=execution.task_intent_id,
        scheduled_for=execution.scheduled_for,
        status=str(execution.status),
        attempt_number=execution.attempt_count,
        max_attempts=execution.max_attempts,
        created_at=execution.created_at,
        actor_type=execution.actor_type,
        correlation_id=execution.correlation_id,
    )


def _map_exception(exc: Exception) -> ScheduleServiceError:
    """Map generic exceptions into schedule service errors."""
    if isinstance(exc, ScheduleServiceError):
        return exc
    if isinstance(exc, ValueError):
        return _map_value_error(str(exc))
    return ScheduleServiceError(
        "unexpected_error",
        "Unexpected schedule service error.",
        {"error": str(exc)},
    )


def _map_value_error(message: str) -> ScheduleServiceError:
    """Map value errors from lower layers into service errors."""
    normalized = message.strip().lower()
    if normalized in {"schedule not found.", "task intent not found."}:
        return ScheduleNotFoundError(message)
    if normalized in {"actor_type is required.", "channel is required.", "trace_id is required."}:
        return ScheduleActorContextError(message)
    if normalized == "scheduled actor_type is not allowed for schedule mutations.":
        return ScheduleForbiddenError(message)
    if normalized in {
        "summary is required.",
        "task intent is required.",
        "task intent must be provided as taskintentinput.",
        "definition must be provided as scheduledefinitioninput.",
    }:
        return ScheduleValidationError(message)
    return ScheduleValidationError(message)
