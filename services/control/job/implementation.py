"""Concrete Job Service implementation."""

from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeKind,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    ErrorCategory,
    codes,
    conflict_error,
    dependency_error,
    not_found_error,
    validation_error,
)
from packages.brain_shared.ids import generate_ulid_str
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.substrates.postgres.errors import normalize_postgres_error
from services.action.capability_engine.domain import CapabilityInvocationMetadata
from services.action.capability_engine.service import CapabilityEngineService
from services.control.job.component import SERVICE_COMPONENT_ID
from services.control.job.config import JobServiceSettings
from services.control.job.data.runtime import JobPostgresRuntime
from services.control.job.domain import (
    ALLOWED_STATE_TRANSITIONS,
    AuditEventType,
    CallbackResult,
    CallbackStatus,
    ConditionalDefinition,
    ExecutionListResult,
    ExecutionRecord,
    ExecutionStatus,
    HealthDetail,
    HealthStatus,
    JobIntent,
    JobListResult,
    JobMutationAudit,
    JobMutationResult,
    JobRecord,
    JobState,
    PredicateEvaluationRecord,
    PredicateEvaluationStatus,
    PredicateOperator,
    ReviewCategory,
    ReviewItem,
    ReviewOutput,
    ReviewSeverity,
    RunJobNowResult,
    ScheduleDefinition,
    ScheduleType,
    TriggerSource,
    job_action_adapter,
    schedule_definition_adapter,
)
from services.control.job.interfaces import (
    JobProviderAdapter,
    JobRepository,
    ProviderJobPayload,
)
from services.control.job.retry import compute_retry_at, should_retry
from services.control.job.service import JobService
from services.control.job.timing import compute_next_run
from services.control.job.validation import (
    CancelJobRequest,
    CreateJobRequest,
    ExecutionIdRequest,
    HandleCallbackRequest,
    JobIdRequest,
    ListAuditsRequest,
    ListExecutionsRequest,
    ListJobsRequest,
    PauseJobRequest,
    ResumeJobRequest,
    RunJobNowRequest,
    UpdateJobRequest,
)

_LOGGER = get_logger(__name__)
_JOB_CHANNEL = "job"
_PREDICATE_CHANNEL = "job_predicate"
_PREDICATE_DENIED = "deny"
_PREDICATE_ALLOWED = "allow"


class DefaultJobService(JobService):
    """Default Job Service implementation with Postgres authority."""

    def __init__(
        self,
        *,
        settings: JobServiceSettings,
        repository: JobRepository,
        runtime: JobPostgresRuntime,
        capability_engine_service: CapabilityEngineService,
        provider: JobProviderAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._runtime = runtime
        self._provider = provider
        self._capability_engine_service = capability_engine_service

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
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
        request, errors = self._validate_request(
            meta=meta,
            model=CreateJobRequest,
            payload={
                "summary": summary,
                "details": details,
                "origin_reference": origin_reference,
                "schedule_type": schedule_type,
                "timezone": timezone,
                "definition": definition,
                "job_action": job_action,
                "start_state": start_state,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, CreateJobRequest)

        now = datetime.now(UTC)
        try:
            schedule_definition = self._schedule_definition_for_create(request)
            job_action_model = job_action_adapter.validate_python(request.job_action)
            next_run_at = compute_next_run(
                ScheduleType(request.schedule_type),
                schedule_definition,
                reference_time=now,
                timezone_name=request.timezone,
            )

            intent = self._repository.create_job_intent(
                summary=request.summary,
                action_kind=job_action_model.type,
                capability_id=job_action_model.capability_id,
                input_payload_json=job_action_model.input_payload,
                details=request.details,
                origin_reference=request.origin_reference,
                created_by_actor=meta.principal,
                created_at=now,
            )
            job = self._repository.create_job(
                job_intent_id=intent.id,
                schedule_type=request.schedule_type,
                state=request.start_state,
                timezone=request.timezone,
                definition_json=schedule_definition.model_dump(mode="python"),
                next_run_at=next_run_at,
                retry_max_attempts=self._settings.default_max_attempts,
                retry_backoff_strategy=self._settings.default_backoff_strategy,
                retry_backoff_base_seconds=self._settings.default_backoff_base_seconds,
                origin_trace_id=meta.trace_id,
                origin_envelope_id=meta.envelope_id,
                created_at=now,
            )
            audit = self._repository.create_job_mutation_audit(
                job_id=job.id,
                event_type=AuditEventType.create.value,
                actor_type=meta.principal,
                actor_id=None,
                channel=meta.source,
                trace_id=meta.trace_id,
                diff_summary=f"created {request.schedule_type} job in state {request.start_state}",
                notes=None,
                created_at=now,
            )
            if job.state == JobState.active and self._provider is not None:
                self._provider.register_job(payload=_to_provider_payload(job))
            return success(meta=meta, payload=JobMutationResult(job=job, audit=audit))
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="create_job", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
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
        request, errors = self._validate_request(
            meta=meta,
            model=UpdateJobRequest,
            payload={
                "job_id": job_id,
                "timezone": timezone,
                "definition": definition,
                "notes": notes,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, UpdateJobRequest)

        try:
            job = self._repository.get_job(job_id=request.job_id)
            if job is None:
                return self._not_found(
                    meta=meta, entity="job", entity_id=request.job_id
                )
            if job.state not in {JobState.draft, JobState.active}:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"cannot update job in state '{job.state.value}'",
                            code=codes.CONFLICT,
                        )
                    ],
                )

            now = datetime.now(UTC)
            effective_timezone = request.timezone or job.timezone
            effective_definition = (
                self._schedule_definition_for_update(
                    job=job, definition=request.definition
                )
                if request.definition is not None
                else job.definition
            )
            next_run_at = compute_next_run(
                job.schedule_type,
                effective_definition,
                reference_time=now,
                timezone_name=effective_timezone,
            )

            updated = self._repository.update_job(
                job_id=request.job_id,
                timezone=request.timezone,
                definition_json=(
                    effective_definition.model_dump(mode="python")
                    if request.definition is not None
                    else None
                ),
                next_run_at=next_run_at,
                updated_at=now,
            )
            if updated is None:
                return self._not_found(
                    meta=meta, entity="job", entity_id=request.job_id
                )

            audit = self._repository.create_job_mutation_audit(
                job_id=updated.id,
                event_type=AuditEventType.update.value,
                actor_type=meta.principal,
                actor_id=None,
                channel=meta.source,
                trace_id=meta.trace_id,
                diff_summary="updated definition/timezone",
                notes=request.notes,
                created_at=now,
            )
            if updated.state == JobState.active and self._provider is not None:
                self._provider.update_job(payload=_to_provider_payload(updated))
            return success(
                meta=meta, payload=JobMutationResult(job=updated, audit=audit)
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="update_job", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def pause_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        reason: str = "",
    ) -> Envelope[JobMutationResult]:
        """Transition a job from active to paused."""
        request, errors = self._validate_request(
            meta=meta,
            model=PauseJobRequest,
            payload={"job_id": job_id, "reason": reason},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, PauseJobRequest)
        return self._transition_state(
            meta=meta,
            job_id=request.job_id,
            target_state=JobState.paused,
            event_type=AuditEventType.pause,
            notes=request.reason or None,
            clear_next_run=False,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def resume_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobMutationResult]:
        """Transition a job from paused to active and recompute next_run."""
        request, errors = self._validate_request(
            meta=meta,
            model=ResumeJobRequest,
            payload={"job_id": job_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ResumeJobRequest)
        return self._transition_state(
            meta=meta,
            job_id=request.job_id,
            target_state=JobState.active,
            event_type=AuditEventType.resume,
            notes=None,
            clear_next_run=False,
            recompute_next_run=True,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def cancel_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobMutationResult]:
        """Cancel a job and clear its next_run."""
        request, errors = self._validate_request(
            meta=meta,
            model=CancelJobRequest,
            payload={"job_id": job_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, CancelJobRequest)
        return self._transition_state(
            meta=meta,
            job_id=request.job_id,
            target_state=JobState.canceled,
            event_type=AuditEventType.delete,
            notes=None,
            clear_next_run=True,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def run_job_now(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[RunJobNowResult]:
        """Immediately queue an execution for an active or paused job."""
        request, errors = self._validate_request(
            meta=meta,
            model=RunJobNowRequest,
            payload={"job_id": job_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, RunJobNowRequest)

        try:
            job, intent = self._get_job_context(job_id=request.job_id)
            if job.state not in {JobState.active, JobState.paused}:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"run_now requires state active or paused, got '{job.state.value}'",
                            code=codes.CONFLICT,
                        )
                    ],
                )

            execution = self._create_execution(
                job=job,
                meta=meta,
                scheduled_for=datetime.now(UTC),
                trigger_source=TriggerSource.run_now,
                trace_id=generate_ulid_str(),
                parent_envelope_id=meta.envelope_id,
            )
            dispatched = self._dispatch_execution(
                job=job,
                intent=intent,
                execution=execution,
            )
            self._repository.create_job_mutation_audit(
                job_id=job.id,
                event_type=AuditEventType.run_now.value,
                actor_type=meta.principal,
                actor_id=None,
                channel=meta.source,
                trace_id=meta.trace_id,
                diff_summary=f"run_now triggered execution {execution.id}",
                notes=None,
                created_at=datetime.now(UTC),
            )
            return success(
                meta=meta,
                payload=RunJobNowResult(
                    job=self._repository.get_job(job_id=job.id) or job,
                    execution=dispatched,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="run_job_now", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def get_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[JobRecord]:
        """Read one job by id."""
        request, errors = self._validate_request(
            meta=meta,
            model=JobIdRequest,
            payload={"job_id": job_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, JobIdRequest)
        try:
            job = self._repository.get_job(job_id=request.job_id)
            if job is None:
                return self._not_found(
                    meta=meta, entity="job", entity_id=request.job_id
                )
            return success(meta=meta, payload=job)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="get_job", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
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
        request, errors = self._validate_request(
            meta=meta,
            model=ListJobsRequest,
            payload={
                "state": state,
                "schedule_type": schedule_type,
                "limit": limit,
                "cursor": cursor,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListJobsRequest)
        try:
            jobs = self._repository.list_jobs(
                state=request.state,
                schedule_type=request.schedule_type,
                limit=request.limit,
                cursor=request.cursor,
            )
            next_cursor = jobs[-1].id if len(jobs) == request.limit else None
            return success(
                meta=meta, payload=JobListResult(jobs=jobs, cursor=next_cursor)
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="list_jobs", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("execution_id",),
    )
    def get_execution(
        self,
        *,
        meta: EnvelopeMeta,
        execution_id: str,
    ) -> Envelope[ExecutionRecord]:
        """Read one execution by id."""
        request, errors = self._validate_request(
            meta=meta,
            model=ExecutionIdRequest,
            payload={"execution_id": execution_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ExecutionIdRequest)
        try:
            execution = self._repository.get_execution(
                execution_id=request.execution_id
            )
            if execution is None:
                return self._not_found(
                    meta=meta,
                    entity="execution",
                    entity_id=request.execution_id,
                )
            return success(meta=meta, payload=execution)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(meta=meta, operation="get_execution", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def list_executions(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> Envelope[ExecutionListResult]:
        """List executions for one job with cursor pagination."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListExecutionsRequest,
            payload={"job_id": job_id, "limit": limit, "cursor": cursor},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListExecutionsRequest)
        try:
            executions = self._repository.list_executions(
                job_id=request.job_id,
                limit=request.limit,
                cursor=request.cursor,
            )
            next_cursor = (
                executions[-1].id if len(executions) == request.limit else None
            )
            return success(
                meta=meta,
                payload=ExecutionListResult(executions=executions, cursor=next_cursor),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="list_executions", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def list_job_audits(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
    ) -> Envelope[list[JobMutationAudit]]:
        """List mutation audit entries for one job."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListAuditsRequest,
            payload={"job_id": job_id, "limit": limit},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListAuditsRequest)
        try:
            audits = self._repository.list_job_audits(
                job_id=request.job_id, limit=request.limit
            )
            return success(meta=meta, payload=audits)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="list_job_audits", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def list_predicate_evaluations(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        limit: int = 50,
    ) -> Envelope[list[PredicateEvaluationRecord]]:
        """List predicate evaluation records for one conditional job."""
        request, errors = self._validate_request(
            meta=meta,
            model=ListAuditsRequest,
            payload={"job_id": job_id, "limit": limit},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, ListAuditsRequest)
        try:
            evaluations = self._repository.list_predicate_evaluations(
                job_id=request.job_id,
                limit=request.limit,
            )
            return success(meta=meta, payload=evaluations)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta,
                operation="list_predicate_evaluations",
                exc=exc,
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
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
        request, errors = self._validate_request(
            meta=meta,
            model=HandleCallbackRequest,
            payload={
                "job_id": job_id,
                "scheduled_for": scheduled_for,
                "trace_id": trace_id,
                "trigger_source": trigger_source,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, HandleCallbackRequest)

        try:
            existing = self._repository.get_execution_by_job_and_trace(
                job_id=request.job_id,
                trace_id=request.trace_id,
            )
            if existing is not None:
                return success(
                    meta=meta,
                    payload=CallbackResult(
                        status=CallbackStatus.duplicate,
                        execution_id=existing.id,
                    ),
                )

            job, intent = self._get_job_context(job_id=request.job_id)
            if job.state != JobState.active:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"callback rejected: job state is '{job.state.value}', expected 'active'",
                            code=codes.CONFLICT,
                        )
                    ],
                )

            execution = self._create_execution(
                job=job,
                meta=meta,
                scheduled_for=request.scheduled_for,
                trigger_source=TriggerSource(request.trigger_source),
                trace_id=request.trace_id,
                parent_envelope_id=meta.envelope_id,
            )
            self._advance_scheduled_job(job=job, reference_time=request.scheduled_for)
            self._dispatch_execution(job=job, intent=intent, execution=execution)
            return success(
                meta=meta,
                payload=CallbackResult(
                    status=CallbackStatus.accepted,
                    execution_id=execution.id,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta,
                operation="handle_provider_callback",
                exc=exc,
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("job_id",),
    )
    def evaluate_conditional_job(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
    ) -> Envelope[PredicateEvaluationRecord]:
        """Evaluate the predicate for one conditional job and record audit."""
        request, errors = self._validate_request(
            meta=meta,
            model=JobIdRequest,
            payload={"job_id": job_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert isinstance(request, JobIdRequest)

        try:
            job, intent = self._get_job_context(job_id=request.job_id)
            if job.state != JobState.active:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"conditional evaluation requires state active, got '{job.state.value}'",
                            code=codes.CONFLICT,
                        )
                    ],
                )
            if job.schedule_type != ScheduleType.conditional:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"job is not conditional (type={job.schedule_type.value})",
                            code=codes.CONFLICT,
                        )
                    ],
                )

            definition = job.definition
            assert isinstance(definition, ConditionalDefinition)
            self._advance_scheduled_job(job=job, reference_time=datetime.now(UTC))
            evaluation, matched = self._evaluate_predicate(
                job=job,
                intent=intent,
                definition=definition,
                meta=meta,
            )
            if matched:
                execution = self._create_execution(
                    job=job,
                    meta=meta,
                    scheduled_for=datetime.now(UTC),
                    trigger_source=TriggerSource.conditional,
                    trace_id=generate_ulid_str(),
                    parent_envelope_id=meta.envelope_id,
                )
                self._dispatch_execution(job=job, intent=intent, execution=execution)
            return success(meta=meta, payload=evaluation)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta,
                operation="evaluate_conditional_job",
                exc=exc,
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def process_retry_due_jobs(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[list[str]]:
        """Re-queue retry-scheduled executions past their retry_after time."""
        errors = validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            processed_ids: list[str] = []
            for execution in self._repository.list_retry_due_executions(
                now=datetime.now(UTC)
            ):
                job, intent = self._get_job_context(job_id=execution.job_id)
                if not should_retry(
                    attempt_number=execution.attempt_number,
                    max_attempts=execution.max_attempts,
                ):
                    self._finalize_failed_execution(
                        job=job,
                        execution=execution,
                        error=validation_error(
                            "retry exhausted before requeue",
                            code=codes.CONFLICT,
                        ),
                    )
                    processed_ids.append(execution.id)
                    continue

                requeued = self._repository.update_execution_status(
                    execution_id=execution.id,
                    status=ExecutionStatus.queued.value,
                    started_at=None,
                    finished_at=None,
                    retry_after=None,
                    error_message=None,
                    error_code=None,
                    attempt_number=execution.attempt_number + 1,
                )
                if requeued is None:
                    continue
                self._repository.create_execution_audit(
                    execution_id=requeued.id,
                    job_id=requeued.job_id,
                    status=ExecutionStatus.queued.value,
                    attempt_number=requeued.attempt_number,
                    retry_after=None,
                    error_message=None,
                    error_code=None,
                    created_at=datetime.now(UTC),
                )
                self._dispatch_execution(job=job, intent=intent, execution=requeued)
                processed_ids.append(execution.id)

            return success(meta=meta, payload=processed_ids)
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta,
                operation="process_retry_due_jobs",
                exc=exc,
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def review_job_health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[ReviewOutput]:
        """Detect orphaned, failing, and ignored jobs."""
        errors = validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors)
        try:
            now = datetime.now(UTC)
            orphaned = self._repository.get_orphaned_jobs(
                grace_period_hours=self._settings.orphan_grace_period_hours,
                now=now,
            )
            failing = self._repository.get_failing_jobs(
                threshold=self._settings.consecutive_failure_threshold,
                now=now,
            )
            ignored = self._repository.get_ignored_paused_jobs(
                age_days=self._settings.ignored_pause_age_days,
                now=now,
            )
            review_id = self._repository.create_review_output(
                orphaned_count=len(orphaned),
                failing_count=len(failing),
                ignored_count=len(ignored),
                run_at=now,
                created_at=now,
            )
            items: list[ReviewItem] = []
            for job in orphaned:
                item = ReviewItem(
                    job_id=job.id,
                    category=ReviewCategory.orphaned,
                    severity=ReviewSeverity.warning,
                    message=f"next_run_at {job.next_run_at} is past grace period",
                )
                items.append(item)
                self._repository.create_review_item(
                    review_output_id=review_id,
                    job_id=job.id,
                    category=item.category.value,
                    severity=item.severity.value,
                    message=item.message,
                    created_at=now,
                )
            for job in failing:
                item = ReviewItem(
                    job_id=job.id,
                    category=ReviewCategory.failing,
                    severity=ReviewSeverity.error,
                    message=f"failure_count={job.failure_count} >= threshold",
                )
                items.append(item)
                self._repository.create_review_item(
                    review_output_id=review_id,
                    job_id=job.id,
                    category=item.category.value,
                    severity=item.severity.value,
                    message=item.message,
                    created_at=now,
                )
            for job in ignored:
                item = ReviewItem(
                    job_id=job.id,
                    category=ReviewCategory.ignored,
                    severity=ReviewSeverity.info,
                    message=f"paused since {job.updated_at}",
                )
                items.append(item)
                self._repository.create_review_item(
                    review_output_id=review_id,
                    job_id=job.id,
                    category=item.category.value,
                    severity=item.severity.value,
                    message=item.message,
                    created_at=now,
                )
            return success(
                meta=meta,
                payload=ReviewOutput(
                    id=review_id,
                    orphaned_count=len(orphaned),
                    failing_count=len(failing),
                    ignored_count=len(ignored),
                    items=items,
                    run_at=now,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta, operation="review_job_health", exc=exc
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(
        self,
        *,
        meta: EnvelopeMeta,
    ) -> Envelope[HealthStatus]:
        """Return Job Service and provider health state."""
        errors = validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors)
        repo_ok = False
        try:
            repo_ok = self._repository.is_healthy()
        except Exception:  # noqa: BLE001
            repo_ok = False
        provider_ok = True
        if self._provider is not None:
            try:
                provider_ok = self._provider.health().ready
            except Exception:  # noqa: BLE001
                provider_ok = False
        detail = HealthDetail.ok if repo_ok and provider_ok else HealthDetail.degraded
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=repo_ok,
                provider_ready=provider_ok,
                detail=detail,
            ),
        )

    def _transition_state(
        self,
        *,
        meta: EnvelopeMeta,
        job_id: str,
        target_state: JobState,
        event_type: AuditEventType,
        notes: str | None,
        clear_next_run: bool,
        recompute_next_run: bool = False,
    ) -> Envelope[JobMutationResult]:
        """Execute a validated state transition with audit."""
        try:
            job = self._repository.get_job(job_id=job_id)
            if job is None:
                return self._not_found(meta=meta, entity="job", entity_id=job_id)
            allowed = ALLOWED_STATE_TRANSITIONS.get(job.state, frozenset())
            if target_state not in allowed:
                return failure(
                    meta=meta,
                    errors=[
                        conflict_error(
                            f"cannot transition from '{job.state.value}' to '{target_state.value}'",
                            code=codes.CONFLICT,
                        )
                    ],
                )

            now = datetime.now(UTC)
            next_run_at = job.next_run_at
            if clear_next_run:
                next_run_at = None
            elif recompute_next_run:
                next_run_at = compute_next_run(
                    job.schedule_type,
                    job.definition,
                    reference_time=now,
                    timezone_name=job.timezone,
                )
            updated = self._repository.update_job_state(
                job_id=job_id,
                state=target_state.value,
                next_run_at=next_run_at,
                updated_at=now,
            )
            if updated is None:
                return self._not_found(meta=meta, entity="job", entity_id=job_id)
            audit = self._repository.create_job_mutation_audit(
                job_id=job_id,
                event_type=event_type.value,
                actor_type=meta.principal,
                actor_id=None,
                channel=meta.source,
                trace_id=meta.trace_id,
                diff_summary=f"state: {job.state.value} -> {target_state.value}",
                notes=notes,
                created_at=now,
            )
            if self._provider is not None:
                if target_state == JobState.active:
                    self._provider.resume_job(job_id=job_id)
                elif target_state == JobState.paused:
                    self._provider.pause_job(job_id=job_id)
                elif target_state in {JobState.canceled, JobState.archived}:
                    self._provider.delete_job(job_id=job_id)
            return success(
                meta=meta, payload=JobMutationResult(job=updated, audit=audit)
            )
        except Exception as exc:  # noqa: BLE001
            return self._handle_exception(
                meta=meta,
                operation=f"transition_to_{target_state.value}",
                exc=exc,
            )

    def _dispatch_execution(
        self,
        *,
        job: JobRecord,
        intent: JobIntent,
        execution: ExecutionRecord,
    ) -> ExecutionRecord:
        """Run one queued execution through Capability Engine and update state."""
        started_at = datetime.now(UTC)
        running = self._repository.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.running.value,
            started_at=started_at,
            finished_at=None,
            retry_after=None,
            error_message=None,
            error_code=None,
            attempt_number=execution.attempt_number,
        )
        if running is None:
            msg = f"execution not found: {execution.id}"
            raise RuntimeError(msg)
        self._repository.create_execution_audit(
            execution_id=running.id,
            job_id=running.job_id,
            status=ExecutionStatus.running.value,
            attempt_number=running.attempt_number,
            retry_after=None,
            error_message=None,
            error_code=None,
            created_at=started_at,
        )

        capability_meta = self._new_job_execution_meta(intent=intent, execution=running)
        capability_env = self._capability_engine_service.invoke_capability(
            meta=capability_meta,
            capability_id=intent.action.capability_id,
            input_payload=intent.action.input_payload,
            invocation=self._new_invocation_metadata(
                actor=intent.created_by_actor,
                channel=_JOB_CHANNEL,
            ),
        )
        if capability_env.ok and capability_env.payload is not None:
            return self._finalize_successful_execution(job=job, execution=running)

        error = self._primary_error(capability_env.errors)
        if error.retryable and should_retry(
            attempt_number=running.attempt_number,
            max_attempts=running.max_attempts,
        ):
            return self._schedule_retry(job=job, execution=running, error=error)
        return self._finalize_failed_execution(job=job, execution=running, error=error)

    def _evaluate_predicate(
        self,
        *,
        job: JobRecord,
        intent: JobIntent,
        definition: ConditionalDefinition,
        meta: EnvelopeMeta,
    ) -> tuple[PredicateEvaluationRecord, bool]:
        """Resolve one conditional predicate through a read-only capability call."""
        predicate_meta = new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=intent.created_by_actor,
            trace_id=meta.trace_id,
            parent_id=meta.envelope_id,
        )
        describe_env = self._capability_engine_service.describe_capability(
            meta=predicate_meta,
            capability_id=definition.predicate_capability_id,
        )
        if not describe_env.ok or describe_env.payload is None:
            error = self._primary_error(describe_env.errors)
            evaluation = self._repository.create_predicate_evaluation(
                job_id=job.id,
                status=PredicateEvaluationStatus.failed.value,
                predicate_subject=definition.predicate_subject,
                predicate_operator=definition.predicate_operator.value,
                predicate_value=_stringify_value(definition.predicate_value),
                resolved_value=None,
                authorization_decision=_PREDICATE_DENIED,
                error_code=error.code,
                error_message=error.message,
                trace_id=meta.trace_id,
                created_at=datetime.now(UTC),
            )
            return evaluation, False

        descriptor = describe_env.payload.value
        if descriptor.requires_approval or len(descriptor.side_effects) > 0:
            evaluation = self._repository.create_predicate_evaluation(
                job_id=job.id,
                status=PredicateEvaluationStatus.failed.value,
                predicate_subject=definition.predicate_subject,
                predicate_operator=definition.predicate_operator.value,
                predicate_value=_stringify_value(definition.predicate_value),
                resolved_value=None,
                authorization_decision=_PREDICATE_DENIED,
                error_code=codes.POLICY_VIOLATION,
                error_message="predicate capability must be read-only",
                trace_id=meta.trace_id,
                created_at=datetime.now(UTC),
            )
            return evaluation, False

        invoke_env = self._capability_engine_service.invoke_capability(
            meta=predicate_meta,
            capability_id=definition.predicate_capability_id,
            input_payload=definition.predicate_input_payload,
            invocation=self._new_invocation_metadata(
                actor=intent.created_by_actor,
                channel=_PREDICATE_CHANNEL,
            ),
        )
        if not invoke_env.ok or invoke_env.payload is None:
            error = self._primary_error(invoke_env.errors)
            evaluation = self._repository.create_predicate_evaluation(
                job_id=job.id,
                status=PredicateEvaluationStatus.failed.value,
                predicate_subject=definition.predicate_subject,
                predicate_operator=definition.predicate_operator.value,
                predicate_value=_stringify_value(definition.predicate_value),
                resolved_value=None,
                authorization_decision=(
                    _PREDICATE_DENIED
                    if error.category == ErrorCategory.POLICY
                    else _PREDICATE_ALLOWED
                ),
                error_code=error.code,
                error_message=error.message,
                trace_id=meta.trace_id,
                created_at=datetime.now(UTC),
            )
            return evaluation, False

        output = invoke_env.payload.value.output or {}
        resolved_value = _extract_subject_value(output, definition.predicate_subject)
        matched = _evaluate_predicate_operator(
            definition.predicate_operator,
            resolved_value,
            definition.predicate_value,
        )
        evaluation = self._repository.create_predicate_evaluation(
            job_id=job.id,
            status=(
                PredicateEvaluationStatus.matched.value
                if matched
                else PredicateEvaluationStatus.not_matched.value
            ),
            predicate_subject=definition.predicate_subject,
            predicate_operator=definition.predicate_operator.value,
            predicate_value=_stringify_value(definition.predicate_value),
            resolved_value=_stringify_value(resolved_value),
            authorization_decision=_PREDICATE_ALLOWED,
            error_code=None,
            error_message=None,
            trace_id=meta.trace_id,
            created_at=datetime.now(UTC),
        )
        return evaluation, matched

    def _create_execution(
        self,
        *,
        job: JobRecord,
        meta: EnvelopeMeta,
        scheduled_for: datetime,
        trigger_source: TriggerSource,
        trace_id: str,
        parent_envelope_id: str,
    ) -> ExecutionRecord:
        """Persist one queued execution and its initial audit row."""
        execution = self._repository.create_execution(
            job_id=job.id,
            job_intent_id=job.job_intent_id,
            scheduled_for=scheduled_for,
            status=ExecutionStatus.queued.value,
            attempt_number=1,
            max_attempts=job.retry_max_attempts,
            retry_backoff_strategy=job.retry_backoff_strategy.value,
            trace_id=trace_id,
            parent_envelope_id=parent_envelope_id,
            trigger_source=trigger_source.value,
            created_at=datetime.now(UTC),
        )
        self._repository.create_execution_audit(
            execution_id=execution.id,
            job_id=job.id,
            status=ExecutionStatus.queued.value,
            attempt_number=execution.attempt_number,
            retry_after=None,
            error_message=None,
            error_code=None,
            created_at=datetime.now(UTC),
        )
        return execution

    def _finalize_successful_execution(
        self,
        *,
        job: JobRecord,
        execution: ExecutionRecord,
    ) -> ExecutionRecord:
        """Mark one execution succeeded and update job run-state."""
        finished_at = datetime.now(UTC)
        final = self._repository.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.succeeded.value,
            started_at=execution.started_at,
            finished_at=finished_at,
            retry_after=None,
            error_message=None,
            error_code=None,
            attempt_number=execution.attempt_number,
        )
        if final is None:
            msg = f"execution not found: {execution.id}"
            raise RuntimeError(msg)
        self._repository.create_execution_audit(
            execution_id=final.id,
            job_id=final.job_id,
            status=ExecutionStatus.succeeded.value,
            attempt_number=final.attempt_number,
            retry_after=None,
            error_message=None,
            error_code=None,
            created_at=finished_at,
        )
        self._update_job_after_terminal_execution(
            job=job,
            status=ExecutionStatus.succeeded,
            error=None,
            finished_at=finished_at,
        )
        return final

    def _schedule_retry(
        self,
        *,
        job: JobRecord,
        execution: ExecutionRecord,
        error: ErrorDetail,
    ) -> ExecutionRecord:
        """Mark one execution for a future retry."""
        finished_at = datetime.now(UTC)
        retry_after = compute_retry_at(
            finished_at,
            retry_count=execution.attempt_number,
            strategy=job.retry_backoff_strategy,
            base_seconds=job.retry_backoff_base_seconds,
        )
        scheduled = self._repository.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.retry_scheduled.value,
            started_at=execution.started_at,
            finished_at=finished_at,
            retry_after=retry_after,
            error_message=error.message,
            error_code=error.code,
            attempt_number=execution.attempt_number,
        )
        if scheduled is None:
            msg = f"execution not found: {execution.id}"
            raise RuntimeError(msg)
        self._repository.create_execution_audit(
            execution_id=scheduled.id,
            job_id=scheduled.job_id,
            status=ExecutionStatus.retry_scheduled.value,
            attempt_number=scheduled.attempt_number,
            retry_after=retry_after,
            error_message=error.message,
            error_code=error.code,
            created_at=finished_at,
        )
        self._update_job_after_nonterminal_failure(
            job=job,
            status=ExecutionStatus.retry_scheduled,
            error=error,
            finished_at=finished_at,
        )
        return scheduled

    def _finalize_failed_execution(
        self,
        *,
        job: JobRecord,
        execution: ExecutionRecord,
        error: ErrorDetail,
    ) -> ExecutionRecord:
        """Mark one execution failed and update job run-state."""
        finished_at = datetime.now(UTC)
        failed = self._repository.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.failed.value,
            started_at=execution.started_at,
            finished_at=finished_at,
            retry_after=None,
            error_message=error.message,
            error_code=error.code,
            attempt_number=execution.attempt_number,
        )
        if failed is None:
            msg = f"execution not found: {execution.id}"
            raise RuntimeError(msg)
        self._repository.create_execution_audit(
            execution_id=failed.id,
            job_id=failed.job_id,
            status=ExecutionStatus.failed.value,
            attempt_number=failed.attempt_number,
            retry_after=None,
            error_message=error.message,
            error_code=error.code,
            created_at=finished_at,
        )
        self._update_job_after_terminal_execution(
            job=job,
            status=ExecutionStatus.failed,
            error=error,
            finished_at=finished_at,
        )
        return failed

    def _update_job_after_nonterminal_failure(
        self,
        *,
        job: JobRecord,
        status: ExecutionStatus,
        error: ErrorDetail,
        finished_at: datetime,
    ) -> None:
        """Persist job failure counters for retry-scheduled attempts."""
        self._repository.update_job_run_state(
            job_id=job.id,
            last_run_at=finished_at,
            last_run_status=status.value,
            failure_count=job.failure_count + 1,
            last_error_message=error.message,
            next_run_at=job.next_run_at,
            state=None,
            updated_at=finished_at,
        )

    def _update_job_after_terminal_execution(
        self,
        *,
        job: JobRecord,
        status: ExecutionStatus,
        error: ErrorDetail | None,
        finished_at: datetime,
    ) -> None:
        """Persist job state after a terminal execution outcome."""
        target_state: str | None = None
        if job.schedule_type == ScheduleType.one_time:
            target_state = JobState.completed.value
        self._repository.update_job_run_state(
            job_id=job.id,
            last_run_at=finished_at,
            last_run_status=status.value,
            failure_count=0
            if status == ExecutionStatus.succeeded
            else job.failure_count + 1,
            last_error_message=error.message if error is not None else None,
            next_run_at=None
            if job.schedule_type == ScheduleType.one_time
            else job.next_run_at,
            state=target_state,
            updated_at=finished_at,
        )

    def _advance_scheduled_job(
        self, *, job: JobRecord, reference_time: datetime
    ) -> None:
        """Move one scheduled job to its next due instant before dispatch."""
        next_run_at = None
        if job.schedule_type != ScheduleType.one_time:
            next_run_at = compute_next_run(
                job.schedule_type,
                job.definition,
                reference_time=reference_time,
                timezone_name=job.timezone,
            )
        self._repository.update_job_state(
            job_id=job.id,
            state=job.state.value,
            next_run_at=next_run_at,
            updated_at=datetime.now(UTC),
        )

    def _schedule_definition_for_create(
        self, request: CreateJobRequest
    ) -> ScheduleDefinition:
        """Validate and normalize one schedule definition for creation."""
        try:
            return schedule_definition_adapter.validate_python(
                {**request.definition, "type": request.schedule_type}
            )
        except ValidationError as exc:
            raise _validation_error(exc, prefix="definition") from exc

    def _schedule_definition_for_update(
        self,
        *,
        job: JobRecord,
        definition: dict[str, object] | None,
    ) -> ScheduleDefinition:
        """Validate and normalize one schedule definition for update."""
        if definition is None:
            return job.definition
        try:
            return schedule_definition_adapter.validate_python(
                {**definition, "type": job.schedule_type.value}
            )
        except ValidationError as exc:
            raise _validation_error(exc, prefix="definition") from exc

    def _get_job_context(self, *, job_id: str) -> tuple[JobRecord, JobIntent]:
        """Return one job plus its immutable intent record."""
        job = self._repository.get_job(job_id=job_id)
        if job is None:
            msg = f"job not found: {job_id}"
            raise LookupError(msg)
        intent = self._repository.get_job_intent(job_intent_id=job.job_intent_id)
        if intent is None:
            msg = f"job_intent not found: {job.job_intent_id}"
            raise LookupError(msg)
        return job, intent

    def _new_job_execution_meta(
        self,
        *,
        intent: JobIntent,
        execution: ExecutionRecord,
    ) -> EnvelopeMeta:
        """Build one envelope meta for internal scheduled execution dispatch."""
        return new_meta(
            kind=EnvelopeKind.COMMAND,
            source=str(SERVICE_COMPONENT_ID),
            principal=intent.created_by_actor,
            trace_id=execution.trace_id,
            parent_id=execution.parent_envelope_id,
        )

    def _new_invocation_metadata(
        self,
        *,
        actor: str,
        channel: str,
    ) -> CapabilityInvocationMetadata:
        """Build invocation metadata for one Capability Engine call."""
        return CapabilityInvocationMetadata(
            actor=actor,
            source=str(SERVICE_COMPONENT_ID),
            channel=channel,
            invocation_id=generate_ulid_str(),
        )

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any] | None,
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and request payload model."""
        errors = validate_meta(meta)
        if errors:
            return None, errors
        try:
            request = model.model_validate(payload or {})
        except ValidationError as exc:
            return None, [
                validation_error(
                    f"request validation failed: {err['msg']}",
                    code=codes.INVALID_ARGUMENT,
                    metadata={"field": ".".join(str(p) for p in err["loc"])},
                )
                for err in exc.errors()
            ]
        return request, []

    def _not_found(
        self, *, meta: EnvelopeMeta, entity: str, entity_id: str
    ) -> Envelope[Any]:
        """Return canonical not-found envelope."""
        return failure(
            meta=meta,
            errors=[
                not_found_error(
                    f"{entity} not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={f"{entity}_id": entity_id},
                )
            ],
        )

    def _primary_error(self, errors: list[ErrorDetail]) -> ErrorDetail:
        """Choose one representative execution error from an envelope."""
        if errors:
            return errors[0]
        return dependency_error(
            "capability invocation failed", code=codes.DEPENDENCY_FAILURE
        )

    def _handle_exception(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        exc: Exception,
    ) -> Envelope[Any]:
        """Map one runtime exception into structured envelope errors."""
        if isinstance(exc, LookupError):
            message = str(exc)
            if message.startswith("job_intent not found: "):
                return self._not_found(
                    meta=meta,
                    entity="job_intent",
                    entity_id=message.removeprefix("job_intent not found: "),
                )
            if message.startswith("job not found: "):
                return self._not_found(
                    meta=meta,
                    entity="job",
                    entity_id=message.removeprefix("job not found: "),
                )
        if isinstance(exc, ValueError):
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )
        if _is_postgres_error(exc):
            return failure(meta=meta, errors=[normalize_postgres_error(exc)])
        _LOGGER.warning(
            "%s failed due to dependency error: exception_type=%s",
            operation,
            type(exc).__name__,
            exc_info=exc,
        )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    f"{operation} failed",
                    code=codes.DEPENDENCY_FAILURE,
                    metadata={"exception_type": type(exc).__name__},
                )
            ],
        )


def _to_provider_payload(job: JobRecord) -> ProviderJobPayload:
    """Build a provider payload from a job record."""
    return ProviderJobPayload(
        job_id=job.id,
        schedule_type=job.schedule_type.value,
        timezone=job.timezone,
        definition=job.definition.model_dump(mode="python"),
        next_run_at=job.next_run_at,
    )


def _is_postgres_error(exc: Exception) -> bool:
    """Return whether one exception appears to originate from Postgres stack."""
    module = type(exc).__module__
    return module.startswith("sqlalchemy") or module.startswith("psycopg")


def _validation_error(exc: ValidationError, *, prefix: str) -> ValueError:
    """Convert one Pydantic error into a stable ``ValueError`` string."""
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    return ValueError(f"{prefix}.{field}: {first['msg']}")


def _extract_subject_value(output: Any, subject: str) -> Any:
    """Resolve one slash-or-dot-delimited subject path from capability output."""
    segments = [segment for segment in re.split(r"[./]+", subject) if segment]
    current = output
    for segment in segments:
        if isinstance(current, dict):
            if segment not in current:
                return None
            current = current[segment]
            continue
        if isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if index < 0 or index >= len(current):
                return None
            current = current[index]
            continue
        return None
    return current


def _evaluate_predicate_operator(
    operator: PredicateOperator,
    resolved_value: Any,
    expected_value: str | int | float | None,
) -> bool:
    """Evaluate one predicate operator against resolved and expected values."""
    if operator == PredicateOperator.exists:
        return resolved_value is not None
    if operator == PredicateOperator.matches:
        if resolved_value is None or expected_value is None:
            return False
        return re.search(str(expected_value), str(resolved_value)) is not None
    if operator == PredicateOperator.eq:
        return resolved_value == expected_value
    if operator == PredicateOperator.neq:
        return resolved_value != expected_value
    if operator == PredicateOperator.gt:
        return _coerce_numeric(resolved_value) > _coerce_numeric(expected_value)
    if operator == PredicateOperator.gte:
        return _coerce_numeric(resolved_value) >= _coerce_numeric(expected_value)
    if operator == PredicateOperator.lt:
        return _coerce_numeric(resolved_value) < _coerce_numeric(expected_value)
    if operator == PredicateOperator.lte:
        return _coerce_numeric(resolved_value) <= _coerce_numeric(expected_value)
    msg = f"unsupported predicate operator: {operator.value}"
    raise ValueError(msg)


def _coerce_numeric(value: Any) -> float:
    """Normalize one numeric-comparable value to ``float``."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() != "":
        return float(value)
    msg = f"value is not numeric: {value!r}"
    raise ValueError(msg)


def _stringify_value(value: Any) -> str | None:
    """Normalize one predicate value for audit storage."""
    if value is None:
        return None
    return str(value)
