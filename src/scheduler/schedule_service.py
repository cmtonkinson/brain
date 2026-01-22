"""Schedule command handlers for schedule management operations."""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, TypeVar

from sqlalchemy.orm import Session

from models import Schedule, ScheduleAuditLog, TaskIntent
from scheduler import data_access
from scheduler.adapter_interface import (
    ScheduleDefinition,
    SchedulePayload,
    SchedulerAdapter,
    SchedulerAdapterError,
)
from scheduler.schedule_service_interface import (
    ActorContext,
    ExecutionRunNowResult,
    ScheduleAdapterSyncError,
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
    TaskIntentInput,
)
from scheduler.mappers import (
    to_schedule_view as _to_schedule_view,
    to_task_intent_view as _to_task_intent_view,
)

ResultT = TypeVar("ResultT")
logger = logging.getLogger(__name__)


class ScheduleCommandServiceImpl:
    """Schedule command service backed by the scheduler data access layer."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        adapter: SchedulerAdapter,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the command service with a session factory."""
        self._session_factory = session_factory
        self._adapter = adapter
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

        def _post_handler(result: ScheduleMutationResult) -> None:
            _sync_adapter_call(
                self._adapter,
                lambda: self._adapter.register_schedule(_to_adapter_payload(result.schedule)),
                session_factory=self._session_factory,
                schedule_id=result.schedule.id,
                actor=actor,
                event_type="create",
            )
            if result.schedule.state == "paused":
                _sync_adapter_call(
                    self._adapter,
                    lambda: self._adapter.pause_schedule(result.schedule.id),
                    session_factory=self._session_factory,
                    schedule_id=result.schedule.id,
                    actor=actor,
                    event_type="pause",
                )

        return self._execute(handler, post_handler=_post_handler)

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

        return self._execute(
            handler,
            post_handler=lambda result: _sync_adapter_update(
                adapter=self._adapter,
                schedule=result.schedule,
                request=request,
                actor=actor,
                session_factory=self._session_factory,
            ),
        )

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

        return self._execute(
            handler,
            post_handler=lambda result: _sync_adapter_call(
                self._adapter,
                lambda: self._adapter.pause_schedule(result.schedule.id),
                session_factory=self._session_factory,
                schedule_id=result.schedule.id,
                actor=actor,
                event_type="pause",
            ),
        )

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

        return self._execute(
            handler,
            post_handler=lambda result: _sync_adapter_call(
                self._adapter,
                lambda: self._adapter.resume_schedule(result.schedule.id),
                session_factory=self._session_factory,
                schedule_id=result.schedule.id,
                actor=actor,
                event_type="resume",
            ),
        )

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

        return self._execute(
            handler,
            post_handler=lambda result: _sync_adapter_call(
                self._adapter,
                lambda: self._adapter.delete_schedule(result.schedule_id),
                session_factory=self._session_factory,
                schedule_id=result.schedule_id,
                actor=actor,
                event_type="delete",
            ),
        )

    def run_now(
        self,
        request: ScheduleRunNowRequest,
        actor: ActorContext,
    ) -> ExecutionRunNowResult:
        """Trigger a schedule execution immediately."""

        def handler(session: Session) -> ExecutionRunNowResult:
            timestamp = self._now_provider()
            schedule = _fetch_schedule(session, request.schedule_id)
            state = str(schedule.state)
            if state not in {"active", "paused"}:
                raise ScheduleConflictError(
                    "run_now is only allowed for active or paused schedules.",
                    {"schedule_id": schedule.id, "state": str(schedule.state)},
                )
            requested_for = request.requested_for or timestamp
            audit_log_id = data_access.record_schedule_audit(
                session,
                schedule.id,
                _to_data_access_actor(_override_reason(actor, request.reason)),
                event_type="run_now",
                diff_summary="run_now" if state == "active" else f"run_now(state={state})",
                now=timestamp,
            ).id
            return ExecutionRunNowResult(
                schedule_id=schedule.id,
                scheduled_for=requested_for,
                audit_log_id=audit_log_id,
            )

        return self._execute(
            handler,
            post_handler=lambda result: _sync_adapter_call(
                self._adapter,
                lambda: self._adapter.trigger_callback(
                    result.schedule_id,
                    result.scheduled_for,
                    trace_id=actor.trace_id,
                    trigger_source="run_now",
                ),
                session_factory=self._session_factory,
                schedule_id=result.schedule_id,
                actor=actor,
                event_type="run_now",
            ),
        )

    def _execute(
        self,
        handler: Callable[[Session], ResultT],
        *,
        post_handler: Callable[[ResultT], None] | None = None,
    ) -> ResultT:
        """Run a handler inside a managed session with error mapping."""
        with closing(self._session_factory()) as session:
            try:
                result = handler(session)
                session.commit()
            except Exception as exc:
                session.rollback()
                if isinstance(exc, ScheduleServiceError):
                    raise
                raise _map_exception(exc) from exc
        if post_handler:
            post_handler(result)
        return result


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


def _map_exception(exc: Exception) -> ScheduleServiceError:
    """Map generic exceptions into schedule service errors."""
    if isinstance(exc, ScheduleServiceError):
        return exc
    if isinstance(exc, ValueError):
        return _map_value_error(str(exc))
    if isinstance(exc, SchedulerAdapterError):
        return ScheduleAdapterSyncError(
            "Schedule adapter sync failed.",
            {"adapter_code": exc.code, "adapter_details": exc.details},
        )
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


def _to_adapter_definition(definition: ScheduleDefinitionView) -> ScheduleDefinition:
    """Map a schedule definition view into an adapter definition payload."""
    return ScheduleDefinition(
        run_at=definition.run_at,
        interval_count=definition.interval_count,
        interval_unit=definition.interval_unit,
        anchor_at=definition.anchor_at,
        rrule=definition.rrule,
        calendar_anchor_at=definition.calendar_anchor_at,
        predicate_subject=definition.predicate_subject,
        predicate_operator=definition.predicate_operator,
        predicate_value=definition.predicate_value,
        evaluation_interval_count=definition.evaluation_interval_count,
        evaluation_interval_unit=definition.evaluation_interval_unit,
    )


def _to_adapter_payload(schedule: ScheduleView) -> SchedulePayload:
    """Map a schedule view into an adapter registration payload."""
    return SchedulePayload(
        schedule_id=schedule.id,
        schedule_type=schedule.schedule_type,
        timezone=schedule.timezone,
        definition=_to_adapter_definition(schedule.definition),
    )


def _sync_adapter_update(
    *,
    adapter: SchedulerAdapter,
    schedule: ScheduleView,
    request: ScheduleUpdateRequest,
    actor: ActorContext,
    session_factory: Callable[[], Session],
) -> None:
    """Synchronize schedule updates to the adapter."""
    terminal_states = {"canceled", "archived", "completed"}
    state = request.state
    if state in terminal_states:
        _sync_adapter_call(
            adapter,
            lambda: adapter.delete_schedule(schedule.id),
            session_factory=session_factory,
            schedule_id=schedule.id,
            actor=actor,
            event_type="update",
        )
        return

    needs_update = request.definition is not None or request.timezone is not None
    if needs_update:
        _sync_adapter_call(
            adapter,
            lambda: adapter.update_schedule(_to_adapter_payload(schedule)),
            session_factory=session_factory,
            schedule_id=schedule.id,
            actor=actor,
            event_type="update",
        )

    if state == "paused":
        _sync_adapter_call(
            adapter,
            lambda: adapter.pause_schedule(schedule.id),
            session_factory=session_factory,
            schedule_id=schedule.id,
            actor=actor,
            event_type="pause",
        )
    elif state == "active":
        _sync_adapter_call(
            adapter,
            lambda: adapter.resume_schedule(schedule.id),
            session_factory=session_factory,
            schedule_id=schedule.id,
            actor=actor,
            event_type="resume",
        )


def _sync_adapter_call(
    adapter: SchedulerAdapter,
    action: Callable[[], None],
    *,
    session_factory: Callable[[], Session],
    schedule_id: int,
    actor: ActorContext,
    event_type: str,
) -> None:
    """Execute an adapter call and audit any failures."""
    try:
        action()
    except SchedulerAdapterError as exc:
        _record_adapter_failure(
            session_factory=session_factory,
            schedule_id=schedule_id,
            actor=actor,
            event_type=event_type,
            adapter_code=exc.code,
            adapter_message=str(exc),
        )
        raise ScheduleAdapterSyncError(
            "Schedule adapter sync failed.",
            {
                "schedule_id": schedule_id,
                "event_type": event_type,
                "adapter_code": exc.code,
                "adapter_message": str(exc),
                "adapter_details": exc.details,
            },
        ) from exc
    except Exception as exc:
        _record_adapter_failure(
            session_factory=session_factory,
            schedule_id=schedule_id,
            actor=actor,
            event_type=event_type,
            adapter_code="unexpected_error",
            adapter_message=str(exc),
        )
        raise ScheduleAdapterSyncError(
            "Schedule adapter sync failed.",
            {
                "schedule_id": schedule_id,
                "event_type": event_type,
                "adapter_code": "unexpected_error",
                "adapter_message": str(exc),
            },
        ) from exc


def _record_adapter_failure(
    *,
    session_factory: Callable[[], Session],
    schedule_id: int,
    actor: ActorContext,
    event_type: str,
    adapter_code: str,
    adapter_message: str,
) -> None:
    """Persist an audit log entry when adapter sync fails."""
    reason = f"adapter_sync_failed:{event_type}:{adapter_code}"
    diff_summary = reason
    failure_actor = ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        channel=actor.channel,
        trace_id=actor.trace_id,
        request_id=None,
        reason=_merge_reason(actor.reason, adapter_message),
    )
    with closing(session_factory()) as session:
        try:
            data_access.record_schedule_audit(
                session,
                schedule_id,
                _to_data_access_actor(failure_actor),
                event_type=event_type,
                diff_summary=diff_summary,
                now=datetime.now(timezone.utc),
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Failed to record adapter sync audit: %s", exc)


def _merge_reason(original: str | None, adapter_message: str) -> str:
    """Compose a reason string for adapter failure audits."""
    if original:
        return f"{original} | adapter_error: {adapter_message}"
    return f"adapter_error: {adapter_message}"
