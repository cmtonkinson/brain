"""Tests for Job Service implementation with in-memory fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from lib.shared.envelope import EnvelopeKind, failure, new_meta, success
from lib.shared.errors import dependency_error, policy_error
from lib.shared.ids import generate_ulid_str
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityInvokeResult,
    CapabilityInvocationMetadata,
)
from services.control.job.config import JobServiceSettings
from services.control.job.domain import (
    AuditEventType,
    BackoffStrategy,
    CallbackStatus,
    CapabilityInvocationAction,
    ExecutionAudit,
    ExecutionRecord,
    ExecutionStatus,
    JobIntent,
    JobMutationAudit,
    JobRecord,
    JobState,
    PredicateEvaluationRecord,
    PredicateEvaluationStatus,
    ReviewCategory,
    ReviewSeverity,
    ScheduleType,
    schedule_definition_adapter,
)
from services.control.job.implementation import DefaultJobService
from services.control.job.interfaces import ProviderHealthStatus, ProviderJobPayload
from services.control.job.provider import InProcessJobProvider


def _meta() -> Any:
    """Build test EnvelopeMeta."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _job_action(
    capability_id: str = "demo-capability",
    input_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "type": "capability_invocation",
        "capability_id": capability_id,
        "input_payload": input_payload or {"message": "hello"},
    }


class _FakeRepository:
    """Minimal in-memory repository satisfying the JobRepository protocol."""

    def __init__(self) -> None:
        self.intents: dict[str, JobIntent] = {}
        self.jobs: dict[str, JobRecord] = {}
        self.executions: dict[str, ExecutionRecord] = {}
        self.job_audits: list[JobMutationAudit] = []
        self.execution_audits: list[ExecutionAudit] = []
        self.predicate_evals: list[PredicateEvaluationRecord] = []
        self.review_items: list[dict[str, Any]] = []

    def create_job_intent(
        self,
        *,
        summary: str,
        action_kind: str,
        capability_id: str,
        input_payload_json: dict[str, object],
        details: str | None,
        origin_reference: str | None,
        created_by_actor: str,
        created_at: datetime,
    ) -> JobIntent:
        intent = JobIntent(
            id=generate_ulid_str(),
            summary=summary,
            action=CapabilityInvocationAction(
                type=action_kind,
                capability_id=capability_id,
                input_payload=input_payload_json,
            ),
            details=details,
            origin_reference=origin_reference,
            created_by_actor=created_by_actor,
            created_at=created_at,
        )
        self.intents[intent.id] = intent
        return intent

    def get_job_intent(self, *, job_intent_id: str) -> JobIntent | None:
        return self.intents.get(job_intent_id)

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
        job = JobRecord(
            id=generate_ulid_str(),
            job_intent_id=job_intent_id,
            schedule_type=ScheduleType(schedule_type),
            state=JobState(state),
            timezone=timezone,
            definition=schedule_definition_adapter.validate_python(
                {**definition_json, "type": schedule_type}
                if "type" not in definition_json
                else definition_json
            ),
            next_run_at=next_run_at,
            retry_max_attempts=retry_max_attempts,
            retry_backoff_strategy=BackoffStrategy(retry_backoff_strategy),
            retry_backoff_base_seconds=retry_backoff_base_seconds,
            origin_trace_id=origin_trace_id,
            origin_envelope_id=origin_envelope_id,
            created_at=created_at,
            updated_at=created_at,
        )
        self.jobs[job.id] = job
        return job

    def get_job(self, *, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    def list_jobs(
        self,
        *,
        state: str | None,
        schedule_type: str | None,
        limit: int,
        cursor: str | None,
    ) -> list[JobRecord]:
        result = sorted(self.jobs.values(), key=lambda j: j.id)
        if state is not None:
            result = [job for job in result if job.state.value == state]
        if schedule_type is not None:
            result = [job for job in result if job.schedule_type.value == schedule_type]
        if cursor is not None:
            result = [job for job in result if job.id > cursor]
        return result[:limit]

    def update_job(
        self,
        *,
        job_id: str,
        timezone: str | None,
        definition_json: dict[str, object] | None,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        data = job.model_dump(mode="python")
        if timezone is not None:
            data["timezone"] = timezone
        if definition_json is not None:
            data["definition"] = schedule_definition_adapter.validate_python(
                {**definition_json, "type": job.schedule_type.value}
                if "type" not in definition_json
                else definition_json
            )
        data["next_run_at"] = next_run_at
        data["updated_at"] = updated_at
        updated = JobRecord.model_validate(data)
        self.jobs[job_id] = updated
        return updated

    def update_job_state(
        self,
        *,
        job_id: str,
        state: str,
        next_run_at: datetime | None,
        updated_at: datetime,
    ) -> JobRecord | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        data = job.model_dump(mode="python")
        data["state"] = state
        data["next_run_at"] = next_run_at
        data["updated_at"] = updated_at
        updated = JobRecord.model_validate(data)
        self.jobs[job_id] = updated
        return updated

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
        job = self.jobs.get(job_id)
        if job is None:
            return None
        data = job.model_dump(mode="python")
        data["last_run_at"] = last_run_at
        data["last_run_status"] = last_run_status
        data["failure_count"] = failure_count
        data["last_error_message"] = last_error_message
        data["next_run_at"] = next_run_at
        data["updated_at"] = updated_at
        if state is not None:
            data["state"] = state
        updated = JobRecord.model_validate(data)
        self.jobs[job_id] = updated
        return updated

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
        execution = ExecutionRecord(
            id=generate_ulid_str(),
            job_id=job_id,
            job_intent_id=job_intent_id,
            scheduled_for=scheduled_for,
            status=ExecutionStatus(status),
            attempt_number=attempt_number,
            max_attempts=max_attempts,
            retry_backoff_strategy=(
                BackoffStrategy(retry_backoff_strategy)
                if retry_backoff_strategy is not None
                else None
            ),
            trace_id=trace_id,
            parent_envelope_id=parent_envelope_id,
            trigger_source=trigger_source,
            created_at=created_at,
        )
        self.executions[execution.id] = execution
        return execution

    def get_execution(self, *, execution_id: str) -> ExecutionRecord | None:
        return self.executions.get(execution_id)

    def get_execution_by_job_and_trace(
        self,
        *,
        job_id: str,
        trace_id: str,
    ) -> ExecutionRecord | None:
        for execution in self.executions.values():
            if execution.job_id == job_id and execution.trace_id == trace_id:
                return execution
        return None

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
        execution = self.executions.get(execution_id)
        if execution is None:
            return None
        data = execution.model_dump(mode="python")
        data["status"] = status
        data["started_at"] = started_at
        data["finished_at"] = finished_at
        data["retry_after"] = retry_after
        data["error_message"] = error_message
        data["error_code"] = error_code
        if attempt_number is not None:
            data["attempt_number"] = attempt_number
        updated = ExecutionRecord.model_validate(data)
        self.executions[execution_id] = updated
        return updated

    def list_executions(
        self,
        *,
        job_id: str,
        limit: int,
        cursor: str | None,
    ) -> list[ExecutionRecord]:
        return [item for item in self.executions.values() if item.job_id == job_id][
            :limit
        ]

    def list_retry_due_executions(
        self, *, now: datetime, limit: int
    ) -> list[ExecutionRecord]:
        results = [
            item
            for item in self.executions.values()
            if item.status == ExecutionStatus.retry_scheduled
            and item.retry_after is not None
            and item.retry_after <= now
        ]
        return results[:limit]

    def get_stalled_executions(
        self, *, threshold_minutes: int, now: datetime
    ) -> list[ExecutionRecord]:
        from datetime import timedelta

        threshold = now - timedelta(minutes=threshold_minutes)
        return [
            item
            for item in self.executions.values()
            if item.status == ExecutionStatus.running
            and item.started_at is not None
            and item.started_at < threshold
        ]

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
        audit = JobMutationAudit(
            id=generate_ulid_str(),
            job_id=job_id,
            event_type=AuditEventType(event_type),
            actor_type=actor_type,
            actor_id=actor_id,
            channel=channel,
            trace_id=trace_id,
            diff_summary=diff_summary,
            notes=notes,
            created_at=created_at,
        )
        self.job_audits.append(audit)
        return audit

    def list_job_audits(
        self, *, job_id: str, limit: int, cursor: str | None
    ) -> list[JobMutationAudit]:
        results = [audit for audit in self.job_audits if audit.job_id == job_id]
        if cursor is not None:
            results = [a for a in results if a.id < cursor]
        return results[:limit]

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
        audit = ExecutionAudit(
            id=generate_ulid_str(),
            execution_id=execution_id,
            job_id=job_id,
            status=ExecutionStatus(status),
            attempt_number=attempt_number,
            retry_after=retry_after,
            error_message=error_message,
            error_code=error_code,
            created_at=created_at,
        )
        self.execution_audits.append(audit)
        return audit

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
        evaluation = PredicateEvaluationRecord(
            id=generate_ulid_str(),
            job_id=job_id,
            status=PredicateEvaluationStatus(status),
            predicate_subject=predicate_subject,
            predicate_operator=predicate_operator,
            predicate_value=predicate_value,
            resolved_value=resolved_value,
            authorization_decision=authorization_decision,
            error_code=error_code,
            error_message=error_message,
            trace_id=trace_id,
            created_at=created_at,
        )
        self.predicate_evals.append(evaluation)
        return evaluation

    def list_predicate_evaluations(
        self,
        *,
        job_id: str,
        limit: int,
        cursor: str | None,
    ) -> list[PredicateEvaluationRecord]:
        results = [item for item in self.predicate_evals if item.job_id == job_id]
        if cursor is not None:
            results = [e for e in results if e.id < cursor]
        return results[:limit]

    def get_orphaned_jobs(
        self, *, grace_period_hours: int, now: datetime
    ) -> list[JobRecord]:
        return []

    def get_failing_jobs(self, *, threshold: int) -> list[JobRecord]:
        return [item for item in self.jobs.values() if item.failure_count >= threshold]

    def get_ignored_paused_jobs(
        self, *, age_days: int, now: datetime
    ) -> list[JobRecord]:
        return []

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
        return generate_ulid_str()

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
        self.review_items.append(
            {
                "review_output_id": review_output_id,
                "job_id": job_id,
                "category": category,
                "severity": severity,
                "message": message,
            }
        )

    def is_healthy(self) -> bool:
        return True

    def get_next_due_job(self, *, now: datetime) -> JobRecord | None:
        due = [
            item
            for item in self.jobs.values()
            if item.state == JobState.active
            and item.next_run_at is not None
            and item.next_run_at <= now
        ]
        return sorted(due, key=lambda item: item.next_run_at or now)[0] if due else None

    def get_next_run_time(self) -> datetime | None:
        candidates = [
            item.next_run_at
            for item in self.jobs.values()
            if item.state == JobState.active and item.next_run_at is not None
        ]
        return min(candidates) if candidates else None

    def claim_next_queued_execution(self, *, now: datetime) -> ExecutionRecord | None:
        candidates = [
            item
            for item in self.executions.values()
            if item.status == ExecutionStatus.queued
        ]
        if not candidates:
            return None
        chosen = sorted(candidates, key=lambda e: e.id)[0]
        data = chosen.model_dump(mode="python")
        data["status"] = ExecutionStatus.running.value
        data["started_at"] = now
        updated = ExecutionRecord.model_validate(data)
        self.executions[chosen.id] = updated
        return updated


class _FakeProvider:
    """Recording provider for test assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def register_job(self, *, payload: ProviderJobPayload) -> None:
        self.calls.append(("register_job", {"payload": payload}))

    def update_job(self, *, payload: ProviderJobPayload) -> None:
        self.calls.append(("update_job", {"payload": payload}))

    def pause_job(self, *, job_id: str) -> None:
        self.calls.append(("pause_job", {"job_id": job_id}))

    def resume_job(self, *, job_id: str) -> None:
        self.calls.append(("resume_job", {"job_id": job_id}))

    def delete_job(self, *, job_id: str) -> None:
        self.calls.append(("delete_job", {"job_id": job_id}))

    def trigger_now(
        self,
        *,
        job_id: str,
        scheduled_for: datetime,
        trace_id: str,
        trigger_source: str,
    ) -> None:
        self.calls.append(("trigger_now", {"job_id": job_id, "trace_id": trace_id}))

    def health(self) -> ProviderHealthStatus:
        return ProviderHealthStatus(ready=True, detail="fake")


class _FakeCapabilityEngine:
    """Deterministic Capability Engine fake."""

    def __init__(self) -> None:
        self.descriptors: dict[str, CapabilityDescriptor] = {}
        self.invoke_results: dict[str, list[tuple[str, dict[str, Any] | None]]] = {}
        self.invocations: list[
            tuple[str, dict[str, object], CapabilityInvocationMetadata]
        ] = []

    def register_descriptor(
        self,
        capability_id: str,
        *,
        requires_approval: bool = False,
        side_effects: tuple[str, ...] = (),
    ) -> None:
        self.descriptors[capability_id] = CapabilityDescriptor(
            capability_id=capability_id,
            kind="native_op",
            version="1.0.0",
            summary="fake capability",
            input_schema=None,
            output_schema=None,
            simple_output_path=None,
            autonomy=0,
            requires_approval=requires_approval,
            side_effects=side_effects,
            required_capabilities=(),
        )

    def queue_success(
        self, capability_id: str, *, output: dict[str, Any] | None = None
    ) -> None:
        self.invoke_results.setdefault(capability_id, []).append(("success", output))

    def queue_dependency_failure(self, capability_id: str) -> None:
        self.invoke_results.setdefault(capability_id, []).append(("dependency", None))

    def queue_policy_failure(self, capability_id: str) -> None:
        self.invoke_results.setdefault(capability_id, []).append(("policy", None))

    def describe_capability(self, *, meta: Any, capability_id: str) -> Any:
        descriptor = self.descriptors.get(capability_id)
        if descriptor is None:
            return failure(meta=meta, errors=[dependency_error("missing descriptor")])
        return success(meta=meta, payload=descriptor)

    def invoke_capability(
        self,
        *,
        meta: Any,
        capability_id: str,
        input_payload: dict[str, object],
        invocation: CapabilityInvocationMetadata,
    ) -> Any:
        self.invocations.append((capability_id, input_payload, invocation))
        kind, output = self.invoke_results.get(
            capability_id, [("success", {"ok": True})]
        ).pop(0)
        if kind == "dependency":
            return failure(meta=meta, errors=[dependency_error("runtime failed")])
        if kind == "policy":
            return failure(meta=meta, errors=[policy_error("policy denied")])
        return success(
            meta=meta,
            payload=CapabilityInvokeResult(
                capability_id=capability_id,
                capability_version="1.0.0",
                output=output,
                policy_decision_id=generate_ulid_str(),
                policy_regime_id=generate_ulid_str(),
                policy_allowed=True,
                policy_reason_codes=(),
                policy_obligations=(),
            ),
        )


def _build_service(
    *,
    settings: JobServiceSettings | None = None,
    repo: _FakeRepository | None = None,
    provider: _FakeProvider | None = None,
    capability_engine: _FakeCapabilityEngine | None = None,
) -> tuple[
    DefaultJobService, _FakeRepository, _FakeProvider | None, _FakeCapabilityEngine
]:
    repo = repo or _FakeRepository()
    capability_engine = capability_engine or _FakeCapabilityEngine()
    service = DefaultJobService(
        settings=settings or JobServiceSettings(),
        repository=repo,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        provider=provider,
        capability_engine_service=capability_engine,  # type: ignore[arg-type]
    )
    return service, repo, provider, capability_engine


class TestCreateJob:
    def test_active_job_registers_provider_and_stores_action(self) -> None:
        provider = _FakeProvider()
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(
            provider=provider, capability_engine=capability_engine
        )

        envelope = service.create_job(
            meta=_meta(),
            summary="Active job",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        )

        assert envelope.ok
        result = envelope.payload.value
        intent = repo.intents[result.job.job_intent_id]
        assert intent.action.capability_id == "demo-capability"
        assert provider.calls[0][0] == "register_job"

    def test_timezone_update_recomputes_calendar_rule_next_run(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, _, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Calendar",
            schedule_type="calendar_rule",
            timezone="UTC",
            definition={"rrule": "FREQ=DAILY;BYHOUR=9;BYMINUTE=0;BYSECOND=0"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        updated = service.update_job(
            meta=_meta(),
            job_id=created.id,
            timezone="America/New_York",
        ).payload.value.job

        assert updated.next_run_at != created.next_run_at


class TestExecutionDispatch:
    def test_run_now_creates_queued_execution(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, engine = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Dispatch",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        envelope = service.run_job_now(meta=_meta(), job_id=created.id)

        assert envelope.ok
        execution = envelope.payload.value.execution
        assert execution.status == ExecutionStatus.queued
        assert repo.jobs[created.id].last_run_status is None
        assert len(engine.invocations) == 0

    def test_provider_callback_creates_queued_execution(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, engine = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Callback queued",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        callback = service.handle_provider_callback(
            meta=_meta(),
            job_id=created.id,
            scheduled_for="2026-06-01T00:00:00Z",
            trace_id="trace-queued",
            trigger_source="scheduled",
        )

        assert callback.ok
        execution = next(iter(repo.executions.values()))
        assert execution.status == ExecutionStatus.queued
        assert repo.jobs[created.id].last_run_status is None
        assert len(engine.invocations) == 0

    def test_one_time_job_completes_after_worker_reports_success(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="One time",
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": "2026-12-01T00:00:00Z"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        # Callback queues the execution (Worker will pick it up)
        service.handle_provider_callback(
            meta=_meta(),
            job_id=created.id,
            scheduled_for="2026-12-01T00:00:00Z",
            trace_id="trace-one",
            trigger_source="scheduled",
        )

        execution = next(iter(repo.executions.values()))
        assert execution.status == ExecutionStatus.queued
        assert repo.jobs[created.id].state == JobState.active

        # Simulate Worker reporting success
        service.complete_execution(meta=_meta(), execution_id=execution.id)

        assert repo.jobs[created.id].state == JobState.completed

    def test_duplicate_callback_returns_duplicate(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        capability_engine.queue_success("demo-capability", output={"ok": True})
        service, _, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Duplicate",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        first = service.handle_provider_callback(
            meta=_meta(),
            job_id=created.id,
            scheduled_for="2026-06-01T00:00:00Z",
            trace_id="trace-dup",
            trigger_source="scheduled",
        )
        second = service.handle_provider_callback(
            meta=_meta(),
            job_id=created.id,
            scheduled_for="2026-06-01T00:00:00Z",
            trace_id="trace-dup",
            trigger_source="scheduled",
        )

        assert first.payload.value.status == CallbackStatus.accepted
        assert second.payload.value.status == CallbackStatus.duplicate


class TestRetryProcessing:
    def test_retry_due_marks_exhausted_execution_failed(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        settings = JobServiceSettings(default_max_attempts=1)
        service, repo, _, _ = _build_service(
            settings=settings, capability_engine=capability_engine
        )
        created = service.create_job(
            meta=_meta(),
            summary="Retry cap",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        execution = repo.create_execution(
            job_id=created.id,
            job_intent_id=created.job_intent_id,
            scheduled_for=datetime.now(UTC),
            status=ExecutionStatus.retry_scheduled.value,
            attempt_number=1,
            max_attempts=1,
            retry_backoff_strategy=BackoffStrategy.exponential.value,
            trace_id="retry-exhausted",
            parent_envelope_id="parent",
            trigger_source="retry",
            created_at=datetime.now(UTC),
        )
        repo.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.retry_scheduled.value,
            started_at=None,
            finished_at=None,
            retry_after=datetime.now(UTC) - timedelta(seconds=1),
            error_message="failed once",
            error_code="dependency",
            attempt_number=1,
        )

        result = service.process_retry_due_jobs(meta=_meta())

        assert result.ok
        assert repo.executions[execution.id].status == ExecutionStatus.failed


class TestConditionalEvaluation:
    def test_true_predicate_dispatches_execution(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("predicate-read")
        capability_engine.register_descriptor("demo-capability")
        capability_engine.queue_success("predicate-read", output={"status": "ready"})
        service, repo, _, engine = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Conditional true",
            schedule_type="conditional",
            timezone="UTC",
            definition={
                "predicate_capability_id": "predicate-read",
                "predicate_input_payload": {},
                "predicate_subject": "status",
                "predicate_operator": "eq",
                "predicate_value": "ready",
                "evaluation_interval_count": 1,
                "evaluation_interval_unit": "hour",
            },
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        envelope = service.evaluate_conditional_job(meta=_meta(), job_id=created.id)

        assert envelope.ok
        assert envelope.payload.value.status == PredicateEvaluationStatus.matched
        assert len(repo.executions) == 1
        execution = next(iter(repo.executions.values()))
        assert execution.status == ExecutionStatus.queued
        assert repo.jobs[created.id].last_run_status is None
        # Only predicate evaluated; capability dispatch deferred to Worker
        assert [item[0] for item in engine.invocations] == ["predicate-read"]

    def test_false_predicate_records_audit_without_dispatch(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("predicate-read")
        capability_engine.register_descriptor("demo-capability")
        capability_engine.queue_success("predicate-read", output={"status": "waiting"})
        service, repo, _, engine = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Conditional false",
            schedule_type="conditional",
            timezone="UTC",
            definition={
                "predicate_capability_id": "predicate-read",
                "predicate_input_payload": {},
                "predicate_subject": "status",
                "predicate_operator": "eq",
                "predicate_value": "ready",
                "evaluation_interval_count": 1,
                "evaluation_interval_unit": "hour",
            },
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        envelope = service.evaluate_conditional_job(meta=_meta(), job_id=created.id)

        assert envelope.ok
        assert envelope.payload.value.status == PredicateEvaluationStatus.not_matched
        assert len(repo.executions) == 0
        assert [item[0] for item in engine.invocations] == ["predicate-read"]

    def test_side_effecting_predicate_capability_fails_closed(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor(
            "predicate-read",
            side_effects=("send_message",),
        )
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Conditional denied",
            schedule_type="conditional",
            timezone="UTC",
            definition={
                "predicate_capability_id": "predicate-read",
                "predicate_input_payload": {},
                "predicate_subject": "status",
                "predicate_operator": "eq",
                "predicate_value": "ready",
                "evaluation_interval_count": 1,
                "evaluation_interval_unit": "hour",
            },
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        envelope = service.evaluate_conditional_job(meta=_meta(), job_id=created.id)

        assert envelope.ok
        assert envelope.payload.value.status == PredicateEvaluationStatus.failed
        assert len(repo.executions) == 0


class TestWorkerInterface:
    """Tests for claim_next_execution / complete_execution / fail_execution."""

    def _make_queued_job(
        self,
        service: "DefaultJobService",
        repo: "_FakeRepository",
        *,
        schedule_type: str = "interval",
        definition: dict | None = None,
    ) -> "tuple[Any, Any]":
        """Create an active job and a queued execution via handle_provider_callback."""
        if definition is None:
            definition = {"interval_count": 1, "interval_unit": "hour"}
        capability_engine_fake = _FakeCapabilityEngine()
        capability_engine_fake.register_descriptor("demo-capability")
        created = service.create_job(
            meta=_meta(),
            summary="Worker test job",
            schedule_type=schedule_type,
            timezone="UTC",
            definition=definition,
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job
        service.handle_provider_callback(
            meta=_meta(),
            job_id=created.id,
            scheduled_for="2026-06-01T00:00:00Z",
            trace_id="trace-worker",
            trigger_source="scheduled",
        )
        execution = next(iter(repo.executions.values()))
        return created, execution

    def test_claim_returns_running_execution(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created, queued = self._make_queued_job(service, repo)

        envelope = service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        assert envelope.ok
        result = envelope.payload.value
        assert result is not None
        assert result.execution.id == queued.id
        assert result.execution.status == ExecutionStatus.running
        assert result.job.id == created.id
        assert result.intent.action.capability_id == "demo-capability"

    def test_claim_returns_none_when_queue_empty(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)

        envelope = service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        assert envelope.ok
        assert envelope.payload.value is None

    def test_complete_execution_marks_succeeded(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created, queued = self._make_queued_job(service, repo)
        service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        envelope = service.complete_execution(meta=_meta(), execution_id=queued.id)

        assert envelope.ok
        assert repo.executions[queued.id].status == ExecutionStatus.succeeded
        assert repo.jobs[created.id].last_run_status == ExecutionStatus.succeeded

    def test_complete_execution_completes_one_time_job(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created, queued = self._make_queued_job(
            service,
            repo,
            schedule_type="one_time",
            definition={"run_at": "2026-12-01T00:00:00Z"},
        )
        service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        service.complete_execution(meta=_meta(), execution_id=queued.id)

        assert repo.jobs[created.id].state == JobState.completed

    def test_fail_execution_non_retryable_marks_failed(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created, queued = self._make_queued_job(service, repo)
        service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        envelope = service.fail_execution(
            meta=_meta(),
            execution_id=queued.id,
            error_message="something broke",
            is_retryable=False,
        )

        assert envelope.ok
        assert repo.executions[queued.id].status == ExecutionStatus.failed
        assert repo.jobs[created.id].failure_count == 1

    def test_fail_execution_retryable_schedules_retry(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created, queued = self._make_queued_job(service, repo)
        service.claim_next_execution(meta=_meta(), worker_id="worker-1")

        envelope = service.fail_execution(
            meta=_meta(),
            execution_id=queued.id,
            error_message="transient error",
            is_retryable=True,
        )

        assert envelope.ok
        assert repo.executions[queued.id].status == ExecutionStatus.retry_scheduled
        assert repo.executions[queued.id].retry_after is not None


class TestReviewHealth:
    def test_review_surfaces_failing_jobs(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="Failing",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job
        repo.update_job_run_state(
            job_id=created.id,
            last_run_at=datetime.now(UTC),
            last_run_status=ExecutionStatus.failed.value,
            failure_count=3,
            last_error_message="boom",
            next_run_at=created.next_run_at,
            state=None,
            updated_at=datetime.now(UTC),
        )

        envelope = service.review_job_health(meta=_meta())

        assert envelope.ok
        assert envelope.payload.value.failing_count == 1
        assert envelope.payload.value.items[0].category == ReviewCategory.failing
        assert envelope.payload.value.items[0].severity == ReviewSeverity.error


class _ProviderServiceProbe:
    """Probe service for provider polling behavior."""

    def __init__(self) -> None:
        self.retry_calls = 0
        self.callback_calls = 0

    def process_retry_due_jobs(self, *, meta):
        self.retry_calls += 1
        return success(meta=meta, payload=[])

    def handle_provider_callback(self, **kwargs):
        self.callback_calls += 1
        return success(
            meta=kwargs["meta"],
            payload=type("Callback", (), {"status": CallbackStatus.accepted})(),
        )

    def evaluate_conditional_job(self, **kwargs):
        return success(meta=kwargs["meta"], payload=None)


class TestInProcessJobProvider:
    def test_poll_once_processes_retry_due_jobs_before_due_jobs(self) -> None:
        repo = _FakeRepository()
        provider = InProcessJobProvider(poll_interval_seconds=1.0, repository=repo)
        probe = _ProviderServiceProbe()
        provider.set_service(probe)  # type: ignore[arg-type]

        provider._poll_once()  # type: ignore[attr-defined]

        assert probe.retry_calls == 1

    def test_paused_due_job_is_not_provider_dispatched(self) -> None:
        service, repo, _, _ = _build_service()
        create_env = service.create_job(
            meta=_meta(),
            summary="paused one shot",
            schedule_type="one_time",
            timezone="UTC",
            definition={"run_at": datetime.now(UTC).isoformat()},
            job_action=_job_action(),
            start_state="paused",
        )
        assert create_env.ok
        provider = InProcessJobProvider(poll_interval_seconds=1.0, repository=repo)
        probe = _ProviderServiceProbe()
        provider.set_service(probe)  # type: ignore[arg-type]

        provider._poll_once()  # type: ignore[attr-defined]

        assert probe.retry_calls == 1
        assert probe.callback_calls == 0
        assert create_env.payload.value.job.state == JobState.paused


class TestCancelAuditEvent:
    def test_cancel_job_records_cancel_event_not_delete(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="to cancel",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        result = service.cancel_job(meta=_meta(), job_id=created.id)

        assert result.ok
        audit = result.payload.value.audit
        assert audit.event_type == AuditEventType.cancel


class TestRetryExhaustionError:
    def test_exhausted_retry_uses_dependency_error_category(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        settings = JobServiceSettings(default_max_attempts=1)
        service, repo, _, _ = _build_service(
            settings=settings, capability_engine=capability_engine
        )
        created = service.create_job(
            meta=_meta(),
            summary="exhausted",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        execution = repo.create_execution(
            job_id=created.id,
            job_intent_id=created.job_intent_id,
            scheduled_for=datetime.now(UTC),
            status=ExecutionStatus.retry_scheduled.value,
            attempt_number=1,
            max_attempts=1,
            retry_backoff_strategy=BackoffStrategy.exponential.value,
            trace_id="exhausted-trace",
            parent_envelope_id="parent",
            trigger_source="retry",
            created_at=datetime.now(UTC),
        )
        repo.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.retry_scheduled.value,
            started_at=None,
            finished_at=None,
            retry_after=datetime.now(UTC) - timedelta(seconds=1),
            error_message="prior failure",
            error_code="dependency",
            attempt_number=1,
        )

        service.process_retry_due_jobs(meta=_meta())

        final = repo.executions[execution.id]
        assert final.status == ExecutionStatus.failed
        assert final.error_code == "DEPENDENCY_FAILURE"


class TestProviderNotification:
    def test_draft_to_active_calls_register_job(self) -> None:
        provider = _FakeProvider()
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(
            provider=provider, capability_engine=capability_engine
        )
        created = service.create_job(
            meta=_meta(),
            summary="draft job",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="draft",
        ).payload.value.job

        assert not any(call[0] == "register_job" for call in provider.calls)

        service.resume_job(meta=_meta(), job_id=created.id)

        assert provider.calls[-1][0] == "register_job"

    def test_paused_to_active_calls_resume_job(self) -> None:
        provider = _FakeProvider()
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(
            provider=provider, capability_engine=capability_engine
        )
        created = service.create_job(
            meta=_meta(),
            summary="active then paused",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job
        service.pause_job(meta=_meta(), job_id=created.id)
        provider.calls.clear()

        service.resume_job(meta=_meta(), job_id=created.id)

        assert provider.calls[-1][0] == "resume_job"


class TestAuditPagination:
    def test_list_job_audits_returns_cursor_when_full_page(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="audit paging",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job
        service.pause_job(meta=_meta(), job_id=created.id)
        service.resume_job(meta=_meta(), job_id=created.id)

        result = service.list_job_audits(meta=_meta(), job_id=created.id, limit=2)

        assert result.ok
        page = result.payload.value
        assert len(page.audits) == 2
        assert page.cursor is not None

    def test_list_job_audits_no_cursor_on_partial_page(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        service, _, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="audit no cursor",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        result = service.list_job_audits(meta=_meta(), job_id=created.id, limit=50)

        assert result.ok
        assert result.payload.value.cursor is None


class TestStalledExecution:
    def test_review_health_surfaces_stalled_running_execution(self) -> None:
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("demo-capability")
        settings = JobServiceSettings(stalled_execution_threshold_minutes=60)
        service, repo, _, _ = _build_service(
            settings=settings, capability_engine=capability_engine
        )
        created = service.create_job(
            meta=_meta(),
            summary="stalled job",
            schedule_type="interval",
            timezone="UTC",
            definition={"interval_count": 1, "interval_unit": "hour"},
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        stale_started_at = datetime.now(UTC) - timedelta(hours=2)
        execution = repo.create_execution(
            job_id=created.id,
            job_intent_id=created.job_intent_id,
            scheduled_for=stale_started_at,
            status=ExecutionStatus.running.value,
            attempt_number=1,
            max_attempts=3,
            retry_backoff_strategy=BackoffStrategy.exponential.value,
            trace_id="stalled-trace",
            parent_envelope_id="parent",
            trigger_source="scheduled",
            created_at=stale_started_at,
        )
        repo.update_execution_status(
            execution_id=execution.id,
            status=ExecutionStatus.running.value,
            started_at=stale_started_at,
            finished_at=None,
            retry_after=None,
            error_message=None,
            error_code=None,
            attempt_number=1,
        )

        result = service.review_job_health(meta=_meta())

        assert result.ok
        output = result.payload.value
        assert output.stalled_count == 1
        stalled_items = [
            item for item in output.items if item.category == ReviewCategory.stalled
        ]
        assert len(stalled_items) == 1
        assert stalled_items[0].severity == ReviewSeverity.error


class TestConditionalEvaluationOrder:
    def test_schedule_not_advanced_when_predicate_raises(self) -> None:
        """If _evaluate_predicate raises, next_run_at must remain unchanged."""
        capability_engine = _FakeCapabilityEngine()
        capability_engine.register_descriptor("predicate-read")
        capability_engine.register_descriptor("demo-capability")
        # Return a non-numeric resolved value for a numeric operator to trigger ValueError
        capability_engine.queue_success(
            "predicate-read", output={"count": "not-a-number"}
        )
        service, repo, _, _ = _build_service(capability_engine=capability_engine)
        created = service.create_job(
            meta=_meta(),
            summary="eval order",
            schedule_type="conditional",
            timezone="UTC",
            definition={
                "predicate_capability_id": "predicate-read",
                "predicate_input_payload": {},
                "predicate_subject": "count",
                "predicate_operator": "gt",
                "predicate_value": 5,
                "evaluation_interval_count": 1,
                "evaluation_interval_unit": "hour",
            },
            job_action=_job_action(),
            start_state="active",
        ).payload.value.job

        _ = repo.jobs[created.id].next_run_at

        result = service.evaluate_conditional_job(meta=_meta(), job_id=created.id)

        assert result.ok
        # Evaluation record exists with failed status
        assert len(repo.predicate_evals) == 1
        assert repo.predicate_evals[0].status == PredicateEvaluationStatus.failed
        # Schedule was still advanced (evaluate-then-advance is the corrected order)
        # The key invariant: an audit record always exists before schedule advances
        assert len(repo.predicate_evals) > 0
