"""Job Service domain models, enums, and typed contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class ScheduleType(str, Enum):
    """Supported schedule type discriminators."""

    one_time = "one_time"
    interval = "interval"
    calendar_rule = "calendar_rule"
    conditional = "conditional"


class JobState(str, Enum):
    """Job lifecycle states."""

    draft = "draft"
    active = "active"
    paused = "paused"
    canceled = "canceled"
    archived = "archived"
    completed = "completed"


class ExecutionStatus(str, Enum):
    """Execution lifecycle statuses."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    retry_scheduled = "retry_scheduled"
    canceled = "canceled"


class BackoffStrategy(str, Enum):
    """Retry backoff strategy options."""

    fixed = "fixed"
    exponential = "exponential"
    none = "none"


class PredicateOperator(str, Enum):
    """Conditional schedule predicate comparison operators."""

    eq = "eq"
    neq = "neq"
    gt = "gt"
    gte = "gte"
    lt = "lt"
    lte = "lte"
    exists = "exists"
    matches = "matches"


class IntervalUnit(str, Enum):
    """Time units for interval and conditional evaluation cadences."""

    minute = "minute"
    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class AuditEventType(str, Enum):
    """Job mutation audit event types."""

    create = "create"
    update = "update"
    pause = "pause"
    resume = "resume"
    cancel = "cancel"
    delete = "delete"
    run_now = "run_now"


class TriggerSource(str, Enum):
    """Execution trigger source identifiers."""

    run_now = "run_now"
    scheduled = "scheduled"
    retry = "retry"
    conditional = "conditional"


class CallbackStatus(str, Enum):
    """Outcome codes returned by ``handle_provider_callback``."""

    accepted = "accepted"
    duplicate = "duplicate"


class ReviewCategory(str, Enum):
    """Job health review issue categories."""

    orphaned = "orphaned"
    failing = "failing"
    ignored = "ignored"
    stalled = "stalled"


class ReviewSeverity(str, Enum):
    """Job health review issue severity levels."""

    info = "info"
    warning = "warning"
    error = "error"


class HealthDetail(str, Enum):
    """Service health detail codes."""

    ok = "ok"
    degraded = "degraded"


class JobActionType(str, Enum):
    """Executable job action kinds."""

    capability_invocation = "capability_invocation"


class PredicateEvaluationStatus(str, Enum):
    """Conditional predicate evaluation outcomes."""

    matched = "matched"
    not_matched = "not_matched"
    failed = "failed"


ALLOWED_STATE_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.draft: frozenset({JobState.active}),
    JobState.active: frozenset(
        {JobState.paused, JobState.canceled, JobState.completed}
    ),
    JobState.paused: frozenset({JobState.active, JobState.canceled}),
    JobState.canceled: frozenset({JobState.archived}),
    JobState.completed: frozenset({JobState.archived}),
    JobState.archived: frozenset(),
}


class CapabilityInvocationAction(BaseModel):
    """Invoke one registered capability with typed input payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["capability_invocation"] = "capability_invocation"
    capability_id: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    input_payload: dict[str, Any] = Field(default_factory=dict)


JobAction = Annotated[
    CapabilityInvocationAction,
    Field(discriminator="type"),
]

job_action_adapter: TypeAdapter[JobAction] = TypeAdapter(JobAction)


class OneTimeDefinition(BaseModel):
    """One-time schedule: fires once at ``run_at``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["one_time"] = "one_time"
    run_at: datetime


class IntervalDefinition(BaseModel):
    """Interval schedule: fires every ``interval_count`` * ``interval_unit``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["interval"] = "interval"
    interval_count: int = Field(gt=0)
    interval_unit: IntervalUnit
    anchor_at: datetime | None = None


class CalendarRuleDefinition(BaseModel):
    """Calendar-rule schedule: fires per an RRULE string."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["calendar_rule"] = "calendar_rule"
    rrule: str
    calendar_anchor_at: datetime | None = None


class ConditionalDefinition(BaseModel):
    """Conditional schedule: evaluates a read-only capability-backed predicate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["conditional"] = "conditional"
    predicate_capability_id: str = Field(
        min_length=1,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    predicate_input_payload: dict[str, Any] = Field(default_factory=dict)
    predicate_subject: str = Field(min_length=1)
    predicate_operator: PredicateOperator
    predicate_value: str | int | float | None = None
    evaluation_interval_count: int = Field(gt=0)
    evaluation_interval_unit: IntervalUnit

    @model_validator(mode="after")
    def _require_value_for_comparison_operators(self) -> ConditionalDefinition:
        """Require ``predicate_value`` for all operators except ``exists``."""
        if self.predicate_operator != PredicateOperator.exists:
            if self.predicate_value is None:
                msg = (
                    f"predicate_value is required for operator "
                    f"'{self.predicate_operator.value}'"
                )
                raise ValueError(msg)
        return self


ScheduleDefinition = Annotated[
    OneTimeDefinition
    | IntervalDefinition
    | CalendarRuleDefinition
    | ConditionalDefinition,
    Field(discriminator="type"),
]

schedule_definition_adapter: TypeAdapter[ScheduleDefinition] = TypeAdapter(
    ScheduleDefinition
)


class JobIntent(BaseModel):
    """Immutable task description attached to one or more jobs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    summary: str
    action: JobAction
    details: str | None = None
    origin_reference: str | None = None
    created_by_actor: str
    created_at: datetime
    superseded_by_id: str | None = None


class JobRecord(BaseModel):
    """Authoritative job state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    job_intent_id: str
    schedule_type: ScheduleType
    state: JobState
    timezone: str
    definition: ScheduleDefinition
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    last_run_status: ExecutionStatus | None = None
    failure_count: int = 0
    last_error_message: str | None = None
    retry_max_attempts: int
    retry_backoff_strategy: BackoffStrategy
    retry_backoff_base_seconds: int
    origin_trace_id: str
    origin_envelope_id: str
    created_at: datetime
    updated_at: datetime


class ExecutionRecord(BaseModel):
    """One execution attempt of a job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    job_id: str
    job_intent_id: str
    scheduled_for: datetime
    status: ExecutionStatus
    attempt_number: int
    max_attempts: int
    retry_backoff_strategy: BackoffStrategy | None = None
    retry_after: datetime | None = None
    trace_id: str
    parent_envelope_id: str
    trigger_source: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None
    created_at: datetime


class JobMutationAudit(BaseModel):
    """Audit record for a job lifecycle mutation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    job_id: str
    event_type: AuditEventType
    actor_type: str
    actor_id: str | None = None
    channel: str
    trace_id: str
    diff_summary: str | None = None
    notes: str | None = None
    created_at: datetime


class ExecutionAudit(BaseModel):
    """Audit record for an execution status transition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    execution_id: str
    job_id: str
    status: ExecutionStatus
    attempt_number: int
    retry_after: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None
    created_at: datetime


class PredicateEvaluationRecord(BaseModel):
    """Audit record for a conditional job predicate evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    job_id: str
    status: PredicateEvaluationStatus
    predicate_subject: str
    predicate_operator: PredicateOperator
    predicate_value: str | None = None
    resolved_value: str | None = None
    authorization_decision: str
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str
    created_at: datetime


class JobMutationResult(BaseModel):
    """Result of a job command that mutates state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job: JobRecord
    audit: JobMutationAudit


class RunJobNowResult(BaseModel):
    """Result of a run-now command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job: JobRecord
    execution: ExecutionRecord


class CallbackResult(BaseModel):
    """Result of a provider callback handling."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: CallbackStatus
    execution_id: str | None = None


class JobListResult(BaseModel):
    """Paginated job list result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    jobs: list[JobRecord]
    cursor: str | None = None


class ExecutionListResult(BaseModel):
    """Paginated execution list result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    executions: list[ExecutionRecord]
    cursor: str | None = None


class ReviewItem(BaseModel):
    """One issue detected by job health review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    category: ReviewCategory
    severity: ReviewSeverity
    message: str


class ReviewOutput(BaseModel):
    """Summary of a job health review run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    orphaned_count: int
    failing_count: int
    ignored_count: int
    stalled_count: int
    items: list[ReviewItem]
    run_at: datetime


class JobAuditListResult(BaseModel):
    """Paginated job mutation audit list result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    audits: list[JobMutationAudit]
    cursor: str | None = None


class PredicateEvaluationListResult(BaseModel):
    """Paginated predicate evaluation list result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluations: list[PredicateEvaluationRecord]
    cursor: str | None = None


class HealthStatus(BaseModel):
    """Job Service health status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    service_ready: bool
    provider_ready: bool
    detail: HealthDetail


class ClaimExecutionResult(BaseModel):
    """Result of a successful execution claim by a Worker Actor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution: ExecutionRecord
    job: JobRecord
    intent: JobIntent
