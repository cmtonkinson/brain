"""Job Service abstract base class defining the public API."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from services.effect.execution.service import ExecutionService
from services.reason.job.domain import (
    CallbackResult,
    ClaimExecutionResult,
    ExecutionListResult,
    ExecutionRecord,
    HealthStatus,
    JobAuditListResult,
    JobListResult,
    JobMutationResult,
    JobRecord,
    JobState,
    PredicateEvaluationListResult,
    PredicateEvaluationRecord,
    ReviewOutput,
    RunJobNowResult,
)


class JobService(ABC):
    """Public API for job scheduling, execution tracking, and audit."""

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @abstractmethod
    def create_job(
        self,
        *,
        meta: EnvelopeMeta,
        summary: str,
        details: str | None = None,
        origin_reference: str | None = None,
        schedule_type: str,
        timezone: str,
        definition: dict[str, object],
        job_action: dict[str, object],
        start_state: str = JobState.draft.value,
    ) -> Envelope[JobMutationResult]:
        """Create a job intent, job record, and initial audit entry."""

    @abstractmethod
    def update_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        timezone: str | None = None,
        definition: dict[str, object] | None = None,
        notes: str | None = None,
    ) -> Envelope[JobMutationResult]:
        """Update a job definition and/or timezone."""

    @abstractmethod
    def pause_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        reason: str = "",
    ) -> Envelope[JobMutationResult]:
        """Transition a job from active to paused."""

    @abstractmethod
    def resume_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobMutationResult]:
        """Transition a job from paused to active and recompute next_run."""

    @abstractmethod
    def cancel_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobMutationResult]:
        """Cancel a job and clear its next_run."""

    @abstractmethod
    def run_job_now(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[RunJobNowResult]:
        """Immediately queue an execution for an active or paused job."""

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @abstractmethod
    def find_job_by_origin_reference(
        self,
        *,
        meta: EnvelopeMeta,
        origin_reference: str,
    ) -> Envelope[JobRecord | None]:
        """Find the most recent job whose intent matches *origin_reference*."""

    @abstractmethod
    def get_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobRecord]:
        """Read one job by id."""

    @abstractmethod
    def list_jobs(
        self,
        *,
        meta: EnvelopeMeta,
        state: str | None = None,
        schedule_type: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[JobListResult]:
        """List jobs with optional filters and cursor pagination."""

    @abstractmethod
    def get_execution(
        self,
        *,
        meta: EnvelopeMeta,
        execution_id: str,
    ) -> Envelope[ExecutionRecord]:
        """Read one execution by id."""

    @abstractmethod
    def list_executions(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[ExecutionListResult]:
        """List executions for one job with cursor pagination."""

    @abstractmethod
    def list_job_audits(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[JobAuditListResult]:
        """List mutation audit entries for one job."""

    @abstractmethod
    def list_predicate_evaluations(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[PredicateEvaluationListResult]:
        """List predicate evaluation records for one conditional job."""

    # ------------------------------------------------------------------
    # Internal orchestration (public API, not HTTP-published)
    # ------------------------------------------------------------------

    @abstractmethod
    def handle_provider_callback(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        scheduled_for: str,
        trace_id: str,
        trigger_source: str,
    ) -> Envelope[CallbackResult]:
        """Handle an idempotent provider callback for one job execution."""

    @abstractmethod
    def evaluate_conditional_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[PredicateEvaluationRecord]:
        """Evaluate the predicate for one conditional job and record audit."""

    @abstractmethod
    def process_retry_due_jobs(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[list[str]]:
        """Re-queue retry-scheduled executions past their retry_after time."""

    @abstractmethod
    def review_job_health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[ReviewOutput]:
        """Detect orphaned, failing, and ignored jobs."""

    @abstractmethod
    def health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[HealthStatus]:
        """Return Job Service and provider health state."""

    # ------------------------------------------------------------------
    # Worker Actor interface
    # ------------------------------------------------------------------

    @abstractmethod
    def claim_next_execution(
        self,
        *,
        meta: EnvelopeMeta,
        worker_id: str = "worker",
    ) -> Envelope[ClaimExecutionResult | None]:
        """Atomically claim the next queued execution for a Worker Actor.

        Returns a None payload when no queued execution is available.
        Safe to call concurrently from multiple workers.
        """

    @abstractmethod
    def complete_execution(
        self,
        *,
        meta: EnvelopeMeta,
        execution_id: str,
    ) -> Envelope[ExecutionRecord]:
        """Mark one running execution as succeeded and update job run-state."""

    @abstractmethod
    def fail_execution(
        self,
        *,
        meta: EnvelopeMeta,
        execution_id: str,
        error_message: str,
        error_code: str | None = None,
        is_retryable: bool = False,
    ) -> Envelope[ExecutionRecord]:
        """Mark one running execution failed or schedule it for retry."""


def build_job_service(
    *,
    settings: CoreRuntimeSettings,
    execution_service: ExecutionService,
) -> JobService:
    """Build concrete Job Service from typed settings."""
    from services.reason.job.config import resolve_job_service_settings
    from services.reason.job.data import JobPostgresRuntime, PostgresJobRepository
    from services.reason.job.implementation import DefaultJobService
    from services.reason.job.provider import InProcessJobProvider

    service_settings = resolve_job_service_settings(settings)
    runtime = JobPostgresRuntime.from_settings(settings)
    repository = PostgresJobRepository(sessions=runtime.schema_sessions)

    provider = InProcessJobProvider(
        poll_interval_seconds=service_settings.provider_poll_interval_seconds,
        repository=repository,
    )

    service = DefaultJobService(
        settings=service_settings,
        repository=repository,
        runtime=runtime,
        provider=provider,
        execution_service=execution_service,
    )

    provider.set_service(service)
    provider.start()

    return service
