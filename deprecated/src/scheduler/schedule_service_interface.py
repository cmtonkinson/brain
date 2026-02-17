"""Schedule service interface definitions for command and query boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class ScheduleServiceError(Exception):
    """Base exception for schedule service failures."""

    def __init__(self, code: str, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize the error with a machine-readable code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


class ScheduleValidationError(ScheduleServiceError):
    """Raised when schedule inputs fail validation."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize a validation error with optional details."""
        super().__init__("validation_error", message, details)


class ScheduleNotFoundError(ScheduleServiceError):
    """Raised when a requested schedule or related record is missing."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize a not-found error with optional details."""
        super().__init__("not_found", message, details)


class ScheduleConflictError(ScheduleServiceError):
    """Raised when a mutation conflicts with existing schedule state."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize a conflict error with optional details."""
        super().__init__("conflict", message, details)


class ScheduleForbiddenError(ScheduleServiceError):
    """Raised when actor context or policy denies a schedule action."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize a forbidden error with optional details."""
        super().__init__("forbidden", message, details)


class ScheduleImmutableFieldError(ScheduleServiceError):
    """Raised when attempting to mutate immutable schedule fields."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize an immutable-field error with optional details."""
        super().__init__("immutable_field", message, details)


class ScheduleStateTransitionError(ScheduleServiceError):
    """Raised when a schedule state transition is invalid."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize an invalid state transition error with optional details."""
        super().__init__("invalid_state_transition", message, details)


class ScheduleActorContextError(ScheduleServiceError):
    """Raised when the actor context is missing or invalid."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize a missing actor context error with optional details."""
        super().__init__("missing_actor_context", message, details)


class ScheduleAdapterSyncError(ScheduleServiceError):
    """Raised when scheduler adapter synchronization fails."""

    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        """Initialize an adapter sync error with optional details."""
        super().__init__("adapter_error", message, details)


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
    """Input payload for creating a task intent inline with schedule creation."""

    summary: str
    details: str | None = None
    origin_reference: str | None = None


@dataclass(frozen=True)
class TaskIntentView:
    """Read-only view of a task intent."""

    id: int
    summary: str
    details: str | None
    origin_reference: str | None
    creator_actor_type: str
    creator_actor_id: str | None
    creator_channel: str
    created_at: datetime
    superseded_by_intent_id: int | None


@dataclass(frozen=True)
class ScheduleDefinitionInput:
    """Typed schedule definition fields for command requests."""

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
class ScheduleDefinitionView:
    """Read-only view of schedule definition fields."""

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
class ScheduleView:
    """Read-only view of a schedule with audit linkage fields."""

    id: int
    task_intent_id: int
    schedule_type: str
    state: str
    timezone: str
    definition: ScheduleDefinitionView
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None
    failure_count: int
    created_at: datetime
    created_by_actor_type: str
    created_by_actor_id: str | None
    updated_at: datetime
    last_execution_id: int | None
    last_evaluated_at: datetime | None
    last_evaluation_status: str | None
    last_evaluation_error_code: str | None


@dataclass(frozen=True)
class ExecutionView:
    """Read-only view of an execution."""

    id: int
    schedule_id: int
    task_intent_id: int
    scheduled_for: datetime
    status: str
    attempt_number: int
    max_attempts: int
    created_at: datetime
    actor_type: str
    trace_id: str | None


@dataclass(frozen=True)
class ScheduleAuditLogView:
    """Read-only view of a schedule audit log entry."""

    id: int
    schedule_id: int
    task_intent_id: int
    event_type: str
    actor_type: str
    actor_id: str | None
    actor_channel: str
    trace_id: str
    request_id: str | None
    reason: str | None
    diff_summary: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class ExecutionAuditLogView:
    """Read-only view of an execution audit log entry."""

    id: int
    execution_id: int
    schedule_id: int
    task_intent_id: int
    status: str
    scheduled_for: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempt_count: int
    retry_count: int
    max_attempts: int
    failure_count: int
    next_retry_at: datetime | None
    last_error_code: str | None
    last_error_message: str | None
    actor_type: str
    actor_id: str | None
    actor_channel: str
    actor_context: str | None
    trace_id: str
    request_id: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class PredicateEvaluationAuditLogView:
    """Read-only view of a predicate evaluation audit log entry."""

    id: int
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
    created_at: datetime


@dataclass(frozen=True)
class ReviewCriteriaView:
    """Criteria metadata used to detect review issues."""

    orphan_grace_period_seconds: int | None
    consecutive_failure_threshold: int | None
    stale_failure_age_seconds: int | None
    ignored_pause_age_seconds: int | None


@dataclass(frozen=True)
class ReviewOutputView:
    """Read-only view of a review output summary."""

    id: int
    job_execution_id: int | None
    window_start: datetime
    window_end: datetime
    criteria: ReviewCriteriaView
    orphaned_count: int
    failing_count: int
    ignored_count: int
    created_at: datetime


@dataclass(frozen=True)
class ReviewItemView:
    """Read-only view of an individual review item."""

    id: int
    review_output_id: int
    schedule_id: int
    task_intent_id: int
    execution_id: int | None
    issue_type: str
    severity: str
    description: str
    last_error_message: str | None
    created_at: datetime


@dataclass(frozen=True)
class ScheduleCreateRequest:
    """Command request to create a schedule with inline task intent."""

    task_intent: TaskIntentInput
    schedule_type: str
    timezone: str
    definition: ScheduleDefinitionInput
    start_state: str = "active"
    idempotency_key: str | None = None


@dataclass(frozen=True)
class ScheduleUpdateRequest:
    """Command request to update mutable schedule fields."""

    schedule_id: int
    timezone: str | None = None
    definition: ScheduleDefinitionInput | None = None
    state: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class SchedulePauseRequest:
    """Command request to pause a schedule."""

    schedule_id: int
    reason: str | None = None


@dataclass(frozen=True)
class ScheduleResumeRequest:
    """Command request to resume a paused schedule."""

    schedule_id: int
    reason: str | None = None


@dataclass(frozen=True)
class ScheduleDeleteRequest:
    """Command request to delete (cancel) a schedule."""

    schedule_id: int
    reason: str | None = None


@dataclass(frozen=True)
class ScheduleRunNowRequest:
    """Command request to run a schedule immediately."""

    schedule_id: int
    requested_for: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ScheduleGetRequest:
    """Query request to fetch a schedule by id."""

    schedule_id: int


@dataclass(frozen=True)
class ScheduleListRequest:
    """Query request to list schedules with optional filters."""

    state: str | None = None
    schedule_type: str | None = None
    created_by_actor_type: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class TaskIntentGetRequest:
    """Query request to fetch a task intent by id."""

    task_intent_id: int


@dataclass(frozen=True)
class ExecutionGetRequest:
    """Query request to fetch an execution by id."""

    execution_id: int


@dataclass(frozen=True)
class ExecutionListRequest:
    """Query request to list executions with optional filters."""

    schedule_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class ScheduleAuditGetRequest:
    """Query request to fetch a schedule audit log entry by id."""

    schedule_audit_id: int


@dataclass(frozen=True)
class ScheduleAuditListRequest:
    """Query request to list schedule audit log entries."""

    schedule_id: int | None = None
    task_intent_id: int | None = None
    event_type: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class ExecutionAuditGetRequest:
    """Query request to fetch an execution audit log entry by id."""

    execution_audit_id: int


@dataclass(frozen=True)
class ExecutionAuditListRequest:
    """Query request to list execution audit log entries."""

    execution_id: int | None = None
    schedule_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class PredicateEvaluationAuditGetRequest:
    """Query request to fetch a predicate evaluation audit entry by evaluation id."""

    evaluation_id: str


@dataclass(frozen=True)
class PredicateEvaluationAuditListRequest:
    """Query request to list predicate evaluation audit entries."""

    schedule_id: int | None = None
    execution_id: int | None = None
    task_intent_id: int | None = None
    status: str | None = None
    evaluated_after: datetime | None = None
    evaluated_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class ReviewOutputGetRequest:
    """Query request to fetch a review output by id."""

    review_output_id: int
    severity: str | None = None


@dataclass(frozen=True)
class ReviewOutputListRequest:
    """Query request to list review outputs with optional filters."""

    severity: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    cursor: str | None = None


@dataclass(frozen=True)
class ScheduleResult:
    """Result wrapper for schedule reads."""

    schedule: ScheduleView
    task_intent: TaskIntentView


@dataclass(frozen=True)
class ScheduleMutationResult:
    """Result wrapper for schedule mutations with audit linkage."""

    schedule: ScheduleView
    task_intent: TaskIntentView
    audit_log_id: int


@dataclass(frozen=True)
class ScheduleDeleteResult:
    """Result wrapper for schedule deletions."""

    schedule_id: int
    state: str
    audit_log_id: int


@dataclass(frozen=True)
class ScheduleListResult:
    """Result wrapper for schedule listings."""

    schedules: tuple[ScheduleView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class TaskIntentResult:
    """Result wrapper for task intent reads."""

    task_intent: TaskIntentView


@dataclass(frozen=True)
class ExecutionResult:
    """Result wrapper for execution reads."""

    execution: ExecutionView


@dataclass(frozen=True)
class ExecutionRunNowResult:
    """Result wrapper for run-now execution requests with audit linkage."""

    schedule_id: int
    scheduled_for: datetime
    audit_log_id: int


@dataclass(frozen=True)
class ExecutionListResult:
    """Result wrapper for execution listings."""

    executions: tuple[ExecutionView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ScheduleAuditResult:
    """Result wrapper for schedule audit reads."""

    audit_log: ScheduleAuditLogView


@dataclass(frozen=True)
class ScheduleAuditListResult:
    """Result wrapper for schedule audit listings."""

    audit_logs: tuple[ScheduleAuditLogView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ExecutionAuditResult:
    """Result wrapper for execution audit reads."""

    audit_log: ExecutionAuditLogView


@dataclass(frozen=True)
class ExecutionAuditListResult:
    """Result wrapper for execution audit listings."""

    audit_logs: tuple[ExecutionAuditLogView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class PredicateEvaluationAuditResult:
    """Result wrapper for predicate evaluation audit reads."""

    audit_log: PredicateEvaluationAuditLogView


@dataclass(frozen=True)
class PredicateEvaluationAuditListResult:
    """Result wrapper for predicate evaluation audit listings."""

    audit_logs: tuple[PredicateEvaluationAuditLogView, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ReviewOutputResult:
    """Result wrapper for review output reads."""

    review_output: ReviewOutputView
    review_items: tuple[ReviewItemView, ...]


@dataclass(frozen=True)
class ReviewOutputListResult:
    """Result wrapper for review output listings."""

    review_outputs: tuple[ReviewOutputView, ...]
    next_cursor: str | None


class ScheduleCommandService(Protocol):
    """Command interface for schedule mutations and run-now execution."""

    def create_schedule(
        self,
        request: ScheduleCreateRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Create a schedule and task intent from the inline intent payload."""
        ...

    def update_schedule(
        self,
        request: ScheduleUpdateRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Update a schedule's mutable fields."""
        ...

    def pause_schedule(
        self,
        request: SchedulePauseRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Pause a schedule."""
        ...

    def resume_schedule(
        self,
        request: ScheduleResumeRequest,
        actor: ActorContext,
    ) -> ScheduleMutationResult:
        """Resume a paused schedule."""
        ...

    def delete_schedule(
        self,
        request: ScheduleDeleteRequest,
        actor: ActorContext,
    ) -> ScheduleDeleteResult:
        """Delete (cancel) a schedule."""
        ...

    def run_now(
        self,
        request: ScheduleRunNowRequest,
        actor: ActorContext,
    ) -> ExecutionRunNowResult:
        """Trigger a schedule execution immediately."""
        ...


class ScheduleQueryService(Protocol):
    """Query interface for schedule inspection and audit views."""

    def get_schedule(self, request: ScheduleGetRequest) -> ScheduleResult:
        """Fetch a schedule by id."""
        ...

    def list_schedules(self, request: ScheduleListRequest) -> ScheduleListResult:
        """List schedules matching the provided filters."""
        ...

    def get_task_intent(self, request: TaskIntentGetRequest) -> TaskIntentResult:
        """Fetch a task intent by id."""
        ...

    def get_execution(self, request: ExecutionGetRequest) -> ExecutionResult:
        """Fetch an execution by id."""
        ...

    def list_executions(self, request: ExecutionListRequest) -> ExecutionListResult:
        """List executions matching the provided filters."""
        ...

    def get_schedule_audit(self, request: ScheduleAuditGetRequest) -> ScheduleAuditResult:
        """Fetch a schedule audit entry by id."""
        ...

    def list_schedule_audits(self, request: ScheduleAuditListRequest) -> ScheduleAuditListResult:
        """List schedule audit entries matching the provided filters."""
        ...

    def get_execution_audit(self, request: ExecutionAuditGetRequest) -> ExecutionAuditResult:
        """Fetch an execution audit entry by id."""
        ...

    def list_execution_audits(self, request: ExecutionAuditListRequest) -> ExecutionAuditListResult:
        """List execution audit entries matching the provided filters."""
        ...

    def get_predicate_evaluation_audit(
        self,
        request: PredicateEvaluationAuditGetRequest,
    ) -> PredicateEvaluationAuditResult:
        """Fetch a predicate evaluation audit entry by evaluation id."""
        ...

    def list_predicate_evaluation_audits(
        self,
        request: PredicateEvaluationAuditListRequest,
    ) -> PredicateEvaluationAuditListResult:
        """List predicate evaluation audit entries matching the provided filters."""
        ...

    def get_review_output(self, request: ReviewOutputGetRequest) -> ReviewOutputResult:
        """Fetch a review output by id."""
        ...

    def list_review_outputs(self, request: ReviewOutputListRequest) -> ReviewOutputListResult:
        """List review outputs matching the provided filters."""
        ...
