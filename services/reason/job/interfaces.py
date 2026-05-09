"""Internal protocols for Job Service repository and provider adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from services.reason.job.domain import (
    ExecutionAudit,
    ExecutionRecord,
    JobIntent,
    JobMutationAudit,
    JobRecord,
    PredicateEvaluationRecord,
)


# ---------------------------------------------------------------------------
# Provider adapter
# ---------------------------------------------------------------------------


class ProviderJobPayload(BaseModel):
    """Payload describing a job for provider registration/update."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: str
    schedule_type: str
    timezone: str
    definition: dict[str, object]
    next_run_at: datetime | None = None


class ProviderHealthStatus(BaseModel):
    """Provider health probe result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class JobProviderAdapter(Protocol):
    """Provider-agnostic adapter for job scheduling runtime."""

    def register_job(self, *, payload: ProviderJobPayload) -> None:
        """Register a new job with the provider."""
        ...

    def update_job(self, *, payload: ProviderJobPayload) -> None:
        """Synchronize an updated job with the provider."""
        ...

    def pause_job(self, *, job_id: str) -> None:
        """Pause a job in the provider."""
        ...

    def resume_job(self, *, job_id: str) -> None:
        """Resume a paused job in the provider."""
        ...

    def delete_job(self, *, job_id: str) -> None:
        """Remove a job from the provider."""
        ...

    def trigger_now(
        self,
        *,
        job_id: str,
        scheduled_for: datetime,
        trace_id: str,
        trigger_source: str,
    ) -> None:
        """Trigger an immediate callback for one job."""
        ...

    def health(self) -> ProviderHealthStatus:
        """Return provider health status."""
        ...


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class JobRepository(Protocol):
    """Transport-neutral protocol for Job Service persistence operations."""

    # -- job intents --

    def create_job_intent(
        self,
        *,
        summary: str,
        action_kind: str,
        op_id: str,
        input_payload_json: dict[str, object],
        details: str | None,
        origin_reference: str | None,
        created_by_actor: str,
        created_at: datetime,
    ) -> JobIntent:
        """Persist one job intent."""
        ...

    def get_job_intent(self, *, job_intent_id: str) -> JobIntent | None:
        """Read one job intent by id."""
        ...

    def find_job_by_origin_reference(
        self, *, origin_reference: str
    ) -> JobRecord | None:
        """Find the most recent job whose intent matches *origin_reference*."""
        ...

    # -- jobs --

    def create_job(
        self,
        *,
        job_intent_id: str,
        schedule_type: str,
        state: str,
        timezone: str,
        definition_json: dict[str, object],
        next_run_at: datetime | None,
        retry_max_attempts: int,
        retry_backoff_strategy: str,
        retry_backoff_base_seconds: int,
        origin_trace_id: str,
        origin_envelope_id: str,
        created_at: datetime,
    ) -> JobRecord:
        """Persist one job record."""
        ...

    def get_job(self, *, job_id: str) -> JobRecord | None:
        """Read one job by id."""
        ...

    def list_jobs(
        self,
        *,
        state: str | None,
        schedule_type: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[JobRecord]:
        """List jobs with optional filters and cursor pagination."""
        ...

    def update_job(
        self,
        *,
        job_id: str,
        timezone: str | None,
        definition_json: dict[str, object] | None,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job definition, timezone, and/or next_run."""
        ...

    def update_job_state(
        self,
        *,
        job_id: str,
        state: str,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job state and optionally next_run_at."""
        ...

    def update_job_run_state(
        self,
        *,
        job_id: str,
        last_run_at: datetime,
        last_run_status: str,
        failure_count: int,
        last_error_message: str | None,
        next_run_at: datetime | None,
        state: str | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        """Update job run-state fields after execution completes."""
        ...

    # -- executions --

    def create_execution(
        self,
        *,
        job_id: str,
        job_intent_id: str,
        scheduled_for: datetime,
        status: str,
        attempt_number: int,
        max_attempts: int,
        retry_backoff_strategy: str | None,
        trace_id: str,
        parent_envelope_id: str,
        trigger_source: str,
        created_at: datetime,
    ) -> ExecutionRecord:
        """Persist one execution record."""
        ...

    def get_execution(self, *, execution_id: str) -> ExecutionRecord | None:
        """Read one execution by id."""
        ...

    def get_execution_by_job_and_trace(
        self, *, job_id: str, trace_id: str
    ) -> ExecutionRecord | None:
        """Read one execution by (job_id, trace_id) for idempotency checks."""
        ...

    def update_execution_status(
        self,
        *,
        execution_id: str,
        status: str,
        started_at: datetime | None,
        finished_at: datetime | None,
        retry_after: datetime | None,
        error_message: str | None,
        error_code: str | None,
        attempt_number: int | None,
    ) -> ExecutionRecord | None:
        """Update execution status and related fields."""
        ...

    def list_executions(
        self,
        *,
        job_id: str,
        limit: int,
        cursor: str | None,
    ) -> list[ExecutionRecord]:
        """List executions for one job with cursor pagination."""
        ...

    def list_retry_due_executions(
        self, *, now: datetime, limit: int
    ) -> list[ExecutionRecord]:
        """List executions with status retry_scheduled and retry_after <= now."""
        ...

    def get_stalled_executions(
        self, *, threshold_minutes: int, now: datetime
    ) -> list[ExecutionRecord]:
        """List executions stuck in running state beyond threshold_minutes."""
        ...

    # -- audits --

    def create_job_mutation_audit(
        self,
        *,
        job_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str | None,
        channel: str,
        trace_id: str,
        diff_summary: str | None,
        notes: str | None,
        created_at: datetime,
    ) -> JobMutationAudit:
        """Persist one job mutation audit entry."""
        ...

    def list_job_audits(
        self, *, job_id: str, limit: int, cursor: str | None
    ) -> list[JobMutationAudit]:
        """List mutation audits for one job."""
        ...

    def create_execution_audit(
        self,
        *,
        execution_id: str,
        job_id: str,
        status: str,
        attempt_number: int,
        retry_after: datetime | None,
        error_message: str | None,
        error_code: str | None,
        created_at: datetime,
    ) -> ExecutionAudit:
        """Persist one execution audit entry."""
        ...

    # -- predicate evaluations --

    def create_predicate_evaluation(
        self,
        *,
        job_id: str,
        status: str,
        predicate_subject: str,
        predicate_operator: str,
        predicate_value: str | None,
        resolved_value: str | None,
        authorization_decision: str,
        error_code: str | None,
        error_message: str | None,
        trace_id: str,
        created_at: datetime,
    ) -> PredicateEvaluationRecord:
        """Persist one predicate evaluation audit entry."""
        ...

    def list_predicate_evaluations(
        self, *, job_id: str, limit: int, cursor: str | None
    ) -> list[PredicateEvaluationRecord]:
        """List predicate evaluations for one job."""
        ...

    # -- review --

    def get_orphaned_jobs(
        self, *, grace_period_hours: int, now: datetime
    ) -> list[JobRecord]:
        """List active jobs with next_run_at past due beyond grace period."""
        ...

    def get_failing_jobs(self, *, threshold: int) -> list[JobRecord]:
        """List active jobs with failure_count >= threshold."""
        ...

    def get_ignored_paused_jobs(
        self, *, age_days: int, now: datetime
    ) -> list[JobRecord]:
        """List paused jobs not updated within age_days."""
        ...

    def create_review_output(
        self,
        *,
        orphaned_count: int,
        failing_count: int,
        ignored_count: int,
        stalled_count: int,
        run_at: datetime,
        created_at: datetime,
    ) -> str:
        """Persist one review output and return its id."""
        ...

    def create_review_item(
        self,
        *,
        review_output_id: str,
        job_id: str,
        category: str,
        severity: str,
        message: str,
        created_at: datetime,
    ) -> None:
        """Persist one review item."""
        ...

    # -- health --

    def is_healthy(self) -> bool:
        """Return True when backing store is reachable."""
        ...

    # -- next due job --

    def get_next_due_job(self, *, now: datetime) -> JobRecord | None:
        """Return the active job with the earliest next_run_at <= now."""
        ...

    def get_next_run_time(self) -> datetime | None:
        """Return the earliest next_run_at across all active jobs."""
        ...

    # -- worker claim --

    def claim_next_queued_execution(self, *, now: datetime) -> ExecutionRecord | None:
        """Atomically claim the oldest queued execution, transitioning it to running.

        Uses SELECT ... FOR UPDATE SKIP LOCKED so concurrent callers do not
        double-claim the same execution.  Returns None when no queued execution
        is available.
        """
        ...
