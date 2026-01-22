"""Execution dispatcher for scheduled task callbacks."""

from __future__ import annotations

import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy.orm import Session

from models import Execution, Schedule, TaskIntent
from scheduler import data_access
from scheduler.actor_context import ScheduledActorContext
from scheduler.callback_bridge import DispatcherCallbackPayload
from scheduler.failure_notifications import FailureNotificationService
from scheduler.retry_policy import (
    RetryPolicy,
    compute_retry_at,
    resolve_retry_policy,
    should_retry,
)
from scheduler.schedule_timing import compute_calendar_rule_next_run, compute_interval_next_run

logger = logging.getLogger(__name__)


class ExecutionDispatcherError(Exception):
    """Raised when the execution dispatcher cannot process a callback."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize the error with a machine-readable code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class ExecutionInvocationExecution:
    """Execution metadata for an invocation request."""

    id: int
    schedule_id: int
    task_intent_id: int
    scheduled_for: datetime
    attempt_number: int
    max_attempts: int
    backoff_strategy: str | None
    retry_after: datetime | None
    trace_id: str


@dataclass(frozen=True)
class ExecutionInvocationTaskIntent:
    """Task intent payload for an invocation request."""

    summary: str
    details: str | None
    origin_reference: str | None


@dataclass(frozen=True)
class ExecutionInvocationScheduleDefinition:
    """Typed schedule definition fields for invocation payloads."""

    run_at: datetime | None
    interval_count: int | None
    interval_unit: str | None
    anchor_at: datetime | None
    rrule: str | None
    calendar_anchor_at: datetime | None
    predicate_subject: str | None
    predicate_operator: str | None
    predicate_value: str | None
    evaluation_interval_count: int | None
    evaluation_interval_unit: str | None


@dataclass(frozen=True)
class ExecutionInvocationSchedule:
    """Schedule metadata for an invocation request."""

    schedule_type: str
    timezone: str | None
    definition: ExecutionInvocationScheduleDefinition
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None


@dataclass(frozen=True)
class ExecutionInvocationActorContext:
    """Actor context envelope for scheduled invocation authorization."""

    actor_type: str
    actor_id: str | None
    channel: str
    privilege_level: str
    autonomy_level: str
    trace_id: str
    request_id: str | None


@dataclass(frozen=True)
class ExecutionInvocationMetadata:
    """Metadata describing how the execution was triggered."""

    actual_started_at: datetime
    trigger_source: str
    callback_id: str | None


@dataclass(frozen=True)
class ExecutionInvocationRequest:
    """Dispatcher payload sent to the Brain agent for execution."""

    execution: ExecutionInvocationExecution
    task_intent: ExecutionInvocationTaskIntent
    schedule: ExecutionInvocationSchedule
    actor_context: ExecutionInvocationActorContext
    execution_metadata: ExecutionInvocationMetadata


@dataclass(frozen=True)
class ExecutionRetryHint:
    """Retry hint returned by the agent for deferred executions."""

    retry_after: datetime
    backoff_strategy: str


@dataclass(frozen=True)
class ExecutionInvocationError:
    """Error details returned for failed executions."""

    error_code: str
    error_message: str


@dataclass(frozen=True)
class ExecutionInvocationResult:
    """Result envelope returned by the agent."""

    status: str
    result_code: str
    attention_required: bool
    message: str | None = None
    side_effects_summary: str | None = None
    retry_hint: ExecutionRetryHint | None = None
    error: ExecutionInvocationError | None = None


class ExecutionInvoker(Protocol):
    """Protocol for agent invocation clients used by the dispatcher."""

    def invoke_execution(self, request: ExecutionInvocationRequest) -> ExecutionInvocationResult:
        """Invoke the Brain agent for a scheduled execution."""
        ...


@dataclass(frozen=True)
class ExecutionDispatchResult:
    """Outcome of dispatching a scheduler callback."""

    status: str
    execution_id: int
    invocation_request: ExecutionInvocationRequest | None


class ExecutionDispatcher:
    """Execution dispatcher handling scheduler callbacks and agent invocation."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        invoker: ExecutionInvoker,
        *,
        now_provider: Callable[[], datetime] | None = None,
        retry_policy: RetryPolicy | None = None,
        failure_notifier: FailureNotificationService | None = None,
    ) -> None:
        """Initialize the dispatcher with persistence and agent invoker access."""
        self._session_factory = session_factory
        self._invoker = invoker
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._retry_policy = resolve_retry_policy(retry_policy)
        self._failure_notifier = failure_notifier

    def dispatch(self, payload: DispatcherCallbackPayload) -> ExecutionDispatchResult:
        """Handle a scheduler callback by persisting execution and invoking the agent."""
        scheduled_context = ScheduledActorContext()
        now = self._now_provider()
        actor_context = _build_execution_actor_context(
            scheduled_context,
            payload,
        )
        with closing(self._session_factory()) as session:
            schedule = _fetch_schedule(session, payload.schedule_id)
            _require_active_schedule(schedule, payload.trigger_source)
            intent = _fetch_task_intent(session, schedule.task_intent_id)
            existing = data_access.get_execution_by_trace_id(
                session,
                payload.schedule_id,
                payload.trace_id,
            )
            if existing is not None:
                return ExecutionDispatchResult(
                    status="duplicate",
                    execution_id=existing.id,
                    invocation_request=None,
                )
            execution = data_access.create_execution(
                session,
                data_access.ExecutionCreateInput(
                    task_intent_id=intent.id,
                    schedule_id=schedule.id,
                    scheduled_for=payload.scheduled_for,
                    status="queued",
                    attempt_count=1,
                    max_attempts=self._retry_policy.max_attempts,
                    retry_backoff_strategy=self._retry_policy.backoff_strategy,
                ),
                actor_context,
                now=now,
            )
            data_access.update_execution(
                session,
                execution.id,
                data_access.ExecutionUpdateInput(
                    status="running",
                    started_at=now,
                ),
                actor_context,
                now=now,
            )
            invocation_request = _build_invocation_request(
                execution,
                schedule,
                intent,
                scheduled_context,
                payload,
                now,
            )
            execution_id = execution.id
            session.commit()

        try:
            invocation_result = self._invoker.invoke_execution(invocation_request)
        except Exception as exc:
            _record_invocation_exception(
                self._session_factory,
                execution_id,
                actor_context,
                exc,
                self._now_provider(),
                self._retry_policy,
            )
            self._notify_failure_if_needed(execution_id)
            raise
        _record_invocation_result(
            self._session_factory,
            execution_id,
            actor_context,
            invocation_result,
            self._now_provider(),
            self._retry_policy,
        )
        self._notify_failure_if_needed(execution_id)
        return ExecutionDispatchResult(
            status="dispatched",
            execution_id=execution_id,
            invocation_request=invocation_request,
        )

    def _notify_failure_if_needed(self, execution_id: int) -> None:
        """Route failure notifications when configured."""
        if self._failure_notifier is None:
            return
        try:
            self._failure_notifier.notify_if_needed(execution_id)
        except Exception:
            logger.exception(
                "Failure notification failed for execution_id=%s.",
                execution_id,
            )


def _fetch_schedule(session: Session, schedule_id: int) -> Schedule:
    """Fetch a schedule or raise a dispatcher error."""
    schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
    if schedule is None:
        raise ExecutionDispatcherError(
            "not_found",
            "schedule not found.",
            {"schedule_id": schedule_id},
        )
    return schedule


def _fetch_task_intent(session: Session, task_intent_id: int) -> TaskIntent:
    """Fetch a task intent or raise a dispatcher error."""
    intent = session.query(TaskIntent).filter(TaskIntent.id == task_intent_id).first()
    if intent is None:
        raise ExecutionDispatcherError(
            "not_found",
            "task intent not found.",
            {"task_intent_id": task_intent_id},
        )
    return intent


def _require_active_schedule(schedule: Schedule, trigger_source: str) -> None:
    """Require a schedule to be active for dispatch unless run_now explicitly allows paused state."""
    state = str(schedule.state)
    if state == "active":
        return
    if trigger_source == "run_now" and state == "paused":
        return
    raise ExecutionDispatcherError(
        "schedule_inactive",
        "schedule must be active to dispatch.",
        {"schedule_id": schedule.id, "state": state},
    )


def _build_invocation_request(
    execution: Execution,
    schedule: Schedule,
    intent: TaskIntent,
    scheduled_context: ScheduledActorContext,
    payload: DispatcherCallbackPayload,
    now: datetime,
) -> ExecutionInvocationRequest:
    """Build the execution invocation request payload."""
    definition = ExecutionInvocationScheduleDefinition(
        run_at=schedule.run_at,
        interval_count=schedule.interval_count,
        interval_unit=str(schedule.interval_unit) if schedule.interval_unit else None,
        anchor_at=schedule.anchor_at,
        rrule=schedule.rrule,
        calendar_anchor_at=schedule.calendar_anchor_at,
        predicate_subject=schedule.predicate_subject,
        predicate_operator=(
            str(schedule.predicate_operator) if schedule.predicate_operator else None
        ),
        predicate_value=schedule.predicate_value,
        evaluation_interval_count=schedule.evaluation_interval_count,
        evaluation_interval_unit=(
            str(schedule.evaluation_interval_unit) if schedule.evaluation_interval_unit else None
        ),
    )
    invocation_execution = ExecutionInvocationExecution(
        id=execution.id,
        schedule_id=execution.schedule_id,
        task_intent_id=execution.task_intent_id,
        scheduled_for=execution.scheduled_for,
        attempt_number=execution.attempt_count,
        max_attempts=execution.max_attempts,
        backoff_strategy=(
            str(execution.retry_backoff_strategy) if execution.retry_backoff_strategy else None
        ),
        retry_after=execution.next_retry_at,
        trace_id=payload.trace_id,
    )
    invocation_schedule = ExecutionInvocationSchedule(
        schedule_type=str(schedule.schedule_type),
        timezone=schedule.timezone,
        definition=definition,
        next_run_at=schedule.next_run_at,
        last_run_at=schedule.last_run_at,
        last_run_status=str(schedule.last_run_status) if schedule.last_run_status else None,
    )
    invocation_task_intent = ExecutionInvocationTaskIntent(
        summary=intent.summary,
        details=intent.details,
        origin_reference=intent.origin_reference,
    )
    invocation_actor_context = ExecutionInvocationActorContext(
        actor_type=scheduled_context.actor_type,
        actor_id=None,
        channel=scheduled_context.channel,
        privilege_level=scheduled_context.privilege_level,
        autonomy_level=scheduled_context.autonomy_level,
        trace_id=payload.trace_id,
        request_id=None,
    )
    invocation_metadata = ExecutionInvocationMetadata(
        actual_started_at=now,
        trigger_source=payload.trigger_source,
        callback_id=payload.trace_id,
    )
    return ExecutionInvocationRequest(
        execution=invocation_execution,
        task_intent=invocation_task_intent,
        schedule=invocation_schedule,
        actor_context=invocation_actor_context,
        execution_metadata=invocation_metadata,
    )


def _build_execution_actor_context(
    scheduled_context: ScheduledActorContext,
    payload: DispatcherCallbackPayload,
) -> data_access.ExecutionActorContext:
    """Build the execution actor context for audit logging."""
    return data_access.ExecutionActorContext(
        actor_type=scheduled_context.actor_type,
        actor_id=None,
        channel=scheduled_context.channel,
        trace_id=payload.trace_id,
        request_id=payload.trace_id,
        actor_context=scheduled_context.to_reference(
            trigger_source=payload.trigger_source,
        ),
    )


def _record_invocation_result(
    session_factory: Callable[[], Session],
    execution_id: int,
    actor_context: data_access.ExecutionActorContext,
    result: ExecutionInvocationResult,
    finished_at: datetime,
    retry_policy: RetryPolicy,
) -> None:
    """Persist execution updates and audit logs from an invocation result."""
    with closing(session_factory()) as session:
        execution = session.query(Execution).filter(Execution.id == execution_id).first()
        if execution is None:
            raise ExecutionDispatcherError(
                "not_found",
                "execution not found.",
                {"execution_id": execution_id},
            )
        updates = _execution_updates_from_result(
            execution,
            result,
            finished_at,
            retry_policy,
        )
        execution = data_access.update_execution(
            session,
            execution_id,
            updates,
            actor_context,
            now=finished_at,
        )
        _update_schedule_for_execution(
            session,
            execution,
            finished_at,
            _build_schedule_update_actor_context(actor_context),
        )
        session.commit()


def _record_invocation_exception(
    session_factory: Callable[[], Session],
    execution_id: int,
    actor_context: data_access.ExecutionActorContext,
    error: Exception,
    finished_at: datetime,
    retry_policy: RetryPolicy,
) -> None:
    """Persist failed execution updates and audit logs for invoker errors."""
    with closing(session_factory()) as session:
        execution = session.query(Execution).filter(Execution.id == execution_id).first()
        if execution is None:
            raise ExecutionDispatcherError(
                "not_found",
                "execution not found.",
                {"execution_id": execution_id},
            )
        updates = _retry_or_fail_updates(
            execution,
            finished_at,
            retry_policy,
            error_code="invoker_exception",
            error_message=str(error),
        )
        execution = data_access.update_execution(
            session,
            execution_id,
            updates,
            actor_context,
            now=finished_at,
        )
        _update_schedule_for_execution(
            session,
            execution,
            finished_at,
            _build_schedule_update_actor_context(actor_context),
        )
        session.commit()


def _execution_updates_from_result(
    execution: Execution,
    result: ExecutionInvocationResult,
    finished_at: datetime,
    retry_policy: RetryPolicy,
) -> data_access.ExecutionUpdateInput:
    """Translate an invocation result into execution update inputs."""
    status = result.status
    if status == "success":
        return data_access.ExecutionUpdateInput(
            status="succeeded",
            finished_at=finished_at,
            last_error_code=None,
            last_error_message=None,
        )
    if status == "failure":
        error_code = result.error.error_code if result.error else result.result_code
        error_message = result.error.error_message if result.error else result.message
        return _retry_or_fail_updates(
            execution,
            finished_at,
            retry_policy,
            error_code=error_code,
            error_message=error_message,
        )
    if status == "deferred":
        error_code = result.error.error_code if result.error else result.result_code
        error_message = result.error.error_message if result.error else result.message
        return _retry_or_fail_updates(
            execution,
            finished_at,
            retry_policy,
            error_code=error_code,
            error_message=error_message,
        )
    return data_access.ExecutionUpdateInput(
        status="failed",
        finished_at=finished_at,
        failure_count=execution.failure_count + 1,
        last_error_code="invalid_result_status",
        last_error_message=f"Unknown invocation status: {status}.",
    )


def _retry_or_fail_updates(
    execution: Execution,
    finished_at: datetime,
    retry_policy: RetryPolicy,
    *,
    error_code: str | None,
    error_message: str | None,
) -> data_access.ExecutionUpdateInput:
    """Return retry updates when allowed, otherwise mark execution failed."""
    failure_count = execution.failure_count + 1
    if not should_retry(execution.attempt_count, execution.max_attempts):
        return data_access.ExecutionUpdateInput(
            status="failed",
            finished_at=finished_at,
            failure_count=failure_count,
            last_error_code=error_code,
            last_error_message=error_message,
        )
    retry_count = execution.retry_count + 1
    backoff_strategy = _resolve_backoff_strategy(execution, retry_policy)
    retry_at = compute_retry_at(
        finished_at,
        retry_count,
        backoff_strategy=backoff_strategy,
        backoff_base_seconds=retry_policy.backoff_base_seconds,
    )
    return data_access.ExecutionUpdateInput(
        status="retry_scheduled",
        finished_at=finished_at,
        retry_count=retry_count,
        retry_backoff_strategy=backoff_strategy,
        next_retry_at=retry_at,
        failure_count=failure_count,
        last_error_code=error_code,
        last_error_message=error_message,
    )


def _resolve_backoff_strategy(
    execution: Execution,
    retry_policy: RetryPolicy,
) -> str:
    """Resolve the backoff strategy to use for retry scheduling."""
    if execution.retry_backoff_strategy is not None:
        return str(execution.retry_backoff_strategy)
    return retry_policy.backoff_strategy


def _build_schedule_update_actor_context(
    actor_context: data_access.ExecutionActorContext,
) -> data_access.ActorContext:
    """Build a system actor context for schedule updates."""
    return data_access.ActorContext(
        actor_type="system",
        actor_id=None,
        channel="scheduler",
        trace_id=actor_context.trace_id,
        request_id=actor_context.request_id,
        reason="execution_update",
    )


def _update_schedule_for_execution(
    session: Session,
    execution: Execution,
    finished_at: datetime,
    actor_context: data_access.ActorContext,
) -> None:
    """Update schedule run state based on the execution outcome."""
    schedule = session.query(Schedule).filter(Schedule.id == execution.schedule_id).first()
    if schedule is None:
        raise ExecutionDispatcherError(
            "not_found",
            "schedule not found.",
            {"schedule_id": execution.schedule_id},
        )
    schedule_updates = _schedule_updates_from_execution(
        schedule,
        execution,
        finished_at,
    )
    data_access.update_schedule(
        session,
        schedule.id,
        schedule_updates,
        actor_context,
        now=finished_at,
    )


def _schedule_updates_from_execution(
    schedule: Schedule,
    execution: Execution,
    finished_at: datetime,
) -> data_access.ScheduleUpdateInput:
    """Translate execution outcomes into schedule run-state updates."""
    next_run_at: datetime | object = data_access.UNSET
    state: str | object = data_access.UNSET
    schedule_type = str(schedule.schedule_type)
    if schedule_type == "interval":
        next_run = compute_interval_next_run(
            schedule.interval_count,
            schedule.interval_unit,
            schedule.anchor_at,
            reference_time=execution.scheduled_for,
        )
        if next_run is not None:
            next_run_at = next_run
    elif schedule_type == "calendar_rule":
        next_run = compute_calendar_rule_next_run(
            schedule.rrule,
            schedule.calendar_anchor_at,
            reference_time=execution.scheduled_for,
        )
        if next_run is not None:
            next_run_at = next_run
    elif schedule_type == "one_time":
        next_run_at = None
        if execution.status == "succeeded":
            state = "completed"

    failure_count: int | object = data_access.UNSET
    if execution.status in {"failed", "retry_scheduled"}:
        failure_count = int(schedule.failure_count or 0) + 1
    elif execution.status == "succeeded":
        failure_count = 0

    return data_access.ScheduleUpdateInput(
        last_run_at=finished_at,
        last_run_status=execution.status,
        last_execution_id=execution.id,
        failure_count=failure_count,
        next_run_at=next_run_at,
        state=state,
    )
