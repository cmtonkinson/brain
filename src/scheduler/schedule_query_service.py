"""Schedule query service implementation for read-only inspection and audit views."""

from __future__ import annotations

from contextlib import closing
from typing import Callable

from sqlalchemy.orm import Session

from models import (
    Execution,
    ExecutionAuditLog,
    PredicateEvaluationAuditLog,
    Schedule,
    ScheduleAuditLog,
    TaskIntent,
)
from scheduler import data_access
from scheduler.schedule_service_interface import (
    ExecutionAuditGetRequest,
    ExecutionAuditListRequest,
    ExecutionAuditListResult,
    ExecutionAuditLogView,
    ExecutionAuditResult,
    ExecutionGetRequest,
    ExecutionListRequest,
    ExecutionListResult,
    ExecutionResult,
    ExecutionView,
    PredicateEvaluationAuditGetRequest,
    PredicateEvaluationAuditListRequest,
    PredicateEvaluationAuditListResult,
    PredicateEvaluationAuditLogView,
    PredicateEvaluationAuditResult,
    ScheduleAuditGetRequest,
    ScheduleAuditListRequest,
    ScheduleAuditListResult,
    ScheduleAuditLogView,
    ScheduleAuditResult,
    ScheduleDefinitionView,
    ScheduleGetRequest,
    ScheduleListRequest,
    ScheduleListResult,
    ScheduleNotFoundError,
    ScheduleResult,
    ScheduleServiceError,
    ScheduleView,
    TaskIntentGetRequest,
    TaskIntentResult,
    TaskIntentView,
)


class ScheduleQueryServiceImpl:
    """Schedule query service backed by the scheduler data access layer.

    Provides read-only access to schedules, executions, task intents, and their
    associated audit logs for inspection and debugging purposes.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Initialize the query service with a session factory.

        Args:
            session_factory: Callable that returns a new SQLAlchemy session.
        """
        self._session_factory = session_factory

    def get_schedule(self, request: ScheduleGetRequest) -> ScheduleResult:
        """Fetch a schedule by id with its associated task intent.

        Args:
            request: Query request containing the schedule_id.

        Returns:
            ScheduleResult containing the schedule and task intent views.

        Raises:
            ScheduleNotFoundError: If the schedule or task intent is not found.
        """
        with closing(self._session_factory()) as session:
            schedule = data_access.get_schedule(session, request.schedule_id)
            if schedule is None:
                raise ScheduleNotFoundError(
                    "schedule not found.",
                    {"schedule_id": request.schedule_id},
                )
            task_intent = data_access.get_task_intent(session, schedule.task_intent_id)
            if task_intent is None:
                raise ScheduleNotFoundError(
                    "task intent not found.",
                    {"task_intent_id": schedule.task_intent_id},
                )
            return ScheduleResult(
                schedule=_to_schedule_view(schedule),
                task_intent=_to_task_intent_view(task_intent),
            )

    def list_schedules(self, request: ScheduleListRequest) -> ScheduleListResult:
        """List schedules matching the provided filters.

        Args:
            request: Query request with optional filters and pagination.

        Returns:
            ScheduleListResult containing matching schedules and next cursor.

        Raises:
            ScheduleServiceError: If validation fails for filter values.
        """
        with closing(self._session_factory()) as session:
            try:
                result = data_access.list_schedules(
                    session,
                    data_access.ScheduleListQuery(
                        state=request.state,
                        schedule_type=request.schedule_type,
                        created_by_actor_type=request.created_by_actor_type,
                        created_after=request.created_after,
                        created_before=request.created_before,
                        limit=request.limit,
                        cursor=int(request.cursor) if request.cursor else None,
                    ),
                )
            except ValueError as exc:
                raise ScheduleServiceError(
                    "validation_error", str(exc), {"filter": "schedule_list"}
                ) from exc

            schedule_views = tuple(_to_schedule_view(s) for s in result.schedules)
            next_cursor = str(result.next_cursor) if result.next_cursor else None
            return ScheduleListResult(
                schedules=schedule_views,
                next_cursor=next_cursor,
            )

    def get_task_intent(self, request: TaskIntentGetRequest) -> TaskIntentResult:
        """Fetch a task intent by id.

        Args:
            request: Query request containing the task_intent_id.

        Returns:
            TaskIntentResult containing the task intent view.

        Raises:
            ScheduleNotFoundError: If the task intent is not found.
        """
        with closing(self._session_factory()) as session:
            task_intent = data_access.get_task_intent(session, request.task_intent_id)
            if task_intent is None:
                raise ScheduleNotFoundError(
                    "task intent not found.",
                    {"task_intent_id": request.task_intent_id},
                )
            return TaskIntentResult(task_intent=_to_task_intent_view(task_intent))

    def get_execution(self, request: ExecutionGetRequest) -> ExecutionResult:
        """Fetch an execution by id.

        Args:
            request: Query request containing the execution_id.

        Returns:
            ExecutionResult containing the execution view.

        Raises:
            ScheduleNotFoundError: If the execution is not found.
        """
        with closing(self._session_factory()) as session:
            execution = data_access.get_execution(session, request.execution_id)
            if execution is None:
                raise ScheduleNotFoundError(
                    "execution not found.",
                    {"execution_id": request.execution_id},
                )
            return ExecutionResult(execution=_to_execution_view(execution))

    def list_executions(self, request: ExecutionListRequest) -> ExecutionListResult:
        """List executions matching the provided filters.

        Args:
            request: Query request with optional filters and pagination.

        Returns:
            ExecutionListResult containing matching executions and next cursor.

        Raises:
            ScheduleServiceError: If validation fails for filter values.
        """
        with closing(self._session_factory()) as session:
            try:
                result = data_access.list_executions(
                    session,
                    data_access.ExecutionHistoryQuery(
                        schedule_id=request.schedule_id,
                        task_intent_id=request.task_intent_id,
                        status=request.status,
                        created_after=request.created_after,
                        created_before=request.created_before,
                        limit=request.limit,
                        cursor=int(request.cursor) if request.cursor else None,
                    ),
                )
            except ValueError as exc:
                raise ScheduleServiceError(
                    "validation_error", str(exc), {"filter": "execution_list"}
                ) from exc

            execution_views = tuple(_to_execution_view(e) for e in result.executions)
            next_cursor = str(result.next_cursor) if result.next_cursor else None
            return ExecutionListResult(
                executions=execution_views,
                next_cursor=next_cursor,
            )

    def get_schedule_audit(self, request: ScheduleAuditGetRequest) -> ScheduleAuditResult:
        """Fetch a schedule audit entry by id.

        Args:
            request: Query request containing the schedule_audit_id.

        Returns:
            ScheduleAuditResult containing the audit log view.

        Raises:
            ScheduleNotFoundError: If the audit entry is not found.
        """
        with closing(self._session_factory()) as session:
            audit = data_access.get_schedule_audit(session, request.schedule_audit_id)
            if audit is None:
                raise ScheduleNotFoundError(
                    "schedule audit not found.",
                    {"schedule_audit_id": request.schedule_audit_id},
                )
            return ScheduleAuditResult(audit_log=_to_schedule_audit_view(audit))

    def list_schedule_audits(self, request: ScheduleAuditListRequest) -> ScheduleAuditListResult:
        """List schedule audit entries matching the provided filters.

        Args:
            request: Query request with optional filters and pagination.

        Returns:
            ScheduleAuditListResult containing matching audit logs and next cursor.

        Raises:
            ScheduleServiceError: If validation fails for filter values.
        """
        with closing(self._session_factory()) as session:
            try:
                result = data_access.list_schedule_audits(
                    session,
                    data_access.ScheduleAuditHistoryQuery(
                        schedule_id=request.schedule_id,
                        task_intent_id=request.task_intent_id,
                        event_type=request.event_type,
                        occurred_after=request.occurred_after,
                        occurred_before=request.occurred_before,
                        limit=request.limit,
                        cursor=int(request.cursor) if request.cursor else None,
                    ),
                )
            except ValueError as exc:
                raise ScheduleServiceError(
                    "validation_error", str(exc), {"filter": "schedule_audit_list"}
                ) from exc

            audit_views = tuple(_to_schedule_audit_view(a) for a in result.audit_logs)
            next_cursor = str(result.next_cursor) if result.next_cursor else None
            return ScheduleAuditListResult(
                audit_logs=audit_views,
                next_cursor=next_cursor,
            )

    def get_execution_audit(self, request: ExecutionAuditGetRequest) -> ExecutionAuditResult:
        """Fetch an execution audit entry by id.

        Args:
            request: Query request containing the execution_audit_id.

        Returns:
            ExecutionAuditResult containing the audit log view.

        Raises:
            ScheduleNotFoundError: If the audit entry is not found.
        """
        with closing(self._session_factory()) as session:
            audit = data_access.get_execution_audit(session, request.execution_audit_id)
            if audit is None:
                raise ScheduleNotFoundError(
                    "execution audit not found.",
                    {"execution_audit_id": request.execution_audit_id},
                )
            return ExecutionAuditResult(audit_log=_to_execution_audit_view(audit))

    def list_execution_audits(self, request: ExecutionAuditListRequest) -> ExecutionAuditListResult:
        """List execution audit entries matching the provided filters.

        Args:
            request: Query request with optional filters and pagination.

        Returns:
            ExecutionAuditListResult containing matching audit logs and next cursor.

        Raises:
            ScheduleServiceError: If validation fails for filter values.
        """
        with closing(self._session_factory()) as session:
            try:
                result = data_access.list_execution_audits(
                    session,
                    data_access.ExecutionAuditHistoryQuery(
                        execution_id=request.execution_id,
                        schedule_id=request.schedule_id,
                        task_intent_id=request.task_intent_id,
                        status=request.status,
                        occurred_after=request.occurred_after,
                        occurred_before=request.occurred_before,
                        limit=request.limit,
                        cursor=int(request.cursor) if request.cursor else None,
                    ),
                )
            except ValueError as exc:
                raise ScheduleServiceError(
                    "validation_error", str(exc), {"filter": "execution_audit_list"}
                ) from exc

            audit_views = tuple(_to_execution_audit_view(a) for a in result.audit_logs)
            next_cursor = str(result.next_cursor) if result.next_cursor else None
            return ExecutionAuditListResult(
                audit_logs=audit_views,
                next_cursor=next_cursor,
            )

    def get_predicate_evaluation_audit(
        self, request: PredicateEvaluationAuditGetRequest
    ) -> PredicateEvaluationAuditResult:
        """Fetch a predicate evaluation audit entry by evaluation id.

        Args:
            request: Query request containing the evaluation_id.

        Returns:
            PredicateEvaluationAuditResult containing the audit log view.

        Raises:
            ScheduleNotFoundError: If the audit entry is not found.
        """
        with closing(self._session_factory()) as session:
            audit = data_access.get_predicate_evaluation_audit_by_evaluation_id(
                session, request.evaluation_id
            )
            if audit is None:
                raise ScheduleNotFoundError(
                    "predicate evaluation audit not found.",
                    {"evaluation_id": request.evaluation_id},
                )
            return PredicateEvaluationAuditResult(
                audit_log=_to_predicate_evaluation_audit_view(audit)
            )

    def list_predicate_evaluation_audits(
        self, request: PredicateEvaluationAuditListRequest
    ) -> PredicateEvaluationAuditListResult:
        """List predicate evaluation audit entries matching the provided filters.

        Args:
            request: Query request with optional filters and pagination.

        Returns:
            PredicateEvaluationAuditListResult containing matching audit logs and cursor.

        Raises:
            ScheduleServiceError: If validation fails for filter values.
        """
        with closing(self._session_factory()) as session:
            try:
                result = data_access.list_predicate_evaluation_audits(
                    session,
                    data_access.PredicateEvaluationAuditHistoryQuery(
                        schedule_id=request.schedule_id,
                        execution_id=request.execution_id,
                        task_intent_id=request.task_intent_id,
                        status=request.status,
                        evaluated_after=request.evaluated_after,
                        evaluated_before=request.evaluated_before,
                        limit=request.limit,
                        cursor=int(request.cursor) if request.cursor else None,
                    ),
                )
            except ValueError as exc:
                raise ScheduleServiceError(
                    "validation_error",
                    str(exc),
                    {"filter": "predicate_evaluation_audit_list"},
                ) from exc

            audit_views = tuple(_to_predicate_evaluation_audit_view(a) for a in result.audit_logs)
            next_cursor = str(result.next_cursor) if result.next_cursor else None
            return PredicateEvaluationAuditListResult(
                audit_logs=audit_views,
                next_cursor=next_cursor,
            )


# ============================================================================
# Model to View Conversion Functions
# ============================================================================


def _to_task_intent_view(intent: TaskIntent) -> TaskIntentView:
    """Convert a TaskIntent model to a TaskIntentView."""
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
    """Convert schedule definition fields to a ScheduleDefinitionView."""
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
    """Convert a Schedule model to a ScheduleView."""
    timezone_value = schedule.timezone
    if timezone_value is None:
        timezone_value = "UTC"
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
    """Convert an Execution model to an ExecutionView."""
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
        trace_id=execution.trace_id,
    )


def _to_schedule_audit_view(audit: ScheduleAuditLog) -> ScheduleAuditLogView:
    """Convert a ScheduleAuditLog model to a ScheduleAuditLogView."""
    return ScheduleAuditLogView(
        id=audit.id,
        schedule_id=audit.schedule_id,
        task_intent_id=audit.task_intent_id,
        event_type=str(audit.event_type),
        actor_type=audit.actor_type,
        actor_id=audit.actor_id,
        actor_channel=audit.actor_channel,
        trace_id=audit.trace_id,
        request_id=audit.request_id,
        reason=audit.reason,
        diff_summary=audit.diff_summary,
        occurred_at=audit.occurred_at,
    )


def _to_execution_audit_view(audit: ExecutionAuditLog) -> ExecutionAuditLogView:
    """Convert an ExecutionAuditLog model to an ExecutionAuditLogView."""
    return ExecutionAuditLogView(
        id=audit.id,
        execution_id=audit.execution_id,
        schedule_id=audit.schedule_id,
        task_intent_id=audit.task_intent_id,
        status=str(audit.status),
        scheduled_for=audit.scheduled_for,
        started_at=audit.started_at,
        finished_at=audit.finished_at,
        attempt_count=audit.attempt_count,
        retry_count=audit.retry_count,
        max_attempts=audit.max_attempts,
        failure_count=audit.failure_count,
        next_retry_at=audit.next_retry_at,
        last_error_code=audit.last_error_code,
        last_error_message=audit.last_error_message,
        actor_type=audit.actor_type,
        actor_id=audit.actor_id,
        actor_channel=audit.actor_channel,
        actor_context=audit.actor_context,
        trace_id=audit.trace_id,
        request_id=audit.request_id,
        occurred_at=audit.occurred_at,
    )


def _to_predicate_evaluation_audit_view(
    audit: PredicateEvaluationAuditLog,
) -> PredicateEvaluationAuditLogView:
    """Convert a PredicateEvaluationAuditLog model to a PredicateEvaluationAuditLogView."""
    return PredicateEvaluationAuditLogView(
        id=audit.id,
        evaluation_id=audit.evaluation_id,
        schedule_id=audit.schedule_id,
        execution_id=audit.execution_id,
        task_intent_id=audit.task_intent_id,
        actor_type=audit.actor_type,
        actor_id=audit.actor_id,
        actor_channel=audit.actor_channel,
        actor_privilege_level=audit.actor_privilege_level,
        actor_autonomy_level=audit.actor_autonomy_level,
        trace_id=audit.trace_id,
        request_id=audit.request_id,
        predicate_subject=audit.predicate_subject,
        predicate_operator=str(audit.predicate_operator),
        predicate_value=audit.predicate_value,
        predicate_value_type=str(audit.predicate_value_type),
        evaluation_time=audit.evaluation_time,
        evaluated_at=audit.evaluated_at,
        status=str(audit.status),
        result_code=audit.result_code,
        message=audit.message,
        observed_value=audit.observed_value,
        error_code=audit.error_code,
        error_message=audit.error_message,
        authorization_decision=audit.authorization_decision,
        authorization_reason_code=audit.authorization_reason_code,
        authorization_reason_message=audit.authorization_reason_message,
        authorization_policy_name=audit.authorization_policy_name,
        authorization_policy_version=audit.authorization_policy_version,
        provider_name=audit.provider_name,
        provider_attempt=audit.provider_attempt,
        created_at=audit.created_at,
    )
