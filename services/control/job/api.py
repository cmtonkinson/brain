"""FastAPI route adapters for Job Service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorCategory
from services.control.job.domain import JobState
from services.control.job.service import JobService


# ---------------------------------------------------------------------------
# Private request / response models
# ---------------------------------------------------------------------------


class _MetaFields(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _CreateJobRequest(_MetaFields):
    summary: str
    details: str | None = None
    origin_reference: str | None = None
    schedule_type: str
    timezone: str
    definition: dict[str, Any]
    job_action: dict[str, Any]
    start_state: str = JobState.draft.value


class _JobIdRequest(_MetaFields):
    job_id: str


class _PauseJobRequest(_MetaFields):
    job_id: str
    reason: str = ""


class _ListJobsRequest(_MetaFields):
    state: str | None = None
    schedule_type: str | None = None
    limit: int = 50
    cursor: str | None = None


class _UpdateJobRequest(_MetaFields):
    job_id: str
    timezone: str | None = None
    definition: dict[str, Any] | None = None
    notes: str | None = None


class _ExecutionIdRequest(_MetaFields):
    execution_id: str


class _ListExecutionsRequest(_MetaFields):
    job_id: str
    limit: int = 50
    cursor: str | None = None


class _ListAuditsRequest(_MetaFields):
    job_id: str
    limit: int = 50
    cursor: str | None = None


class _ClaimExecutionRequest(_MetaFields):
    worker_id: str = "worker"


class _FailExecutionRequest(_MetaFields):
    execution_id: str
    error_message: str
    error_code: str | None = None
    is_retryable: bool = False


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _JobResponse(BaseModel):
    payload: dict[str, Any] | None
    errors: list[_ErrorOut]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_routes(*, router: APIRouter, service: JobService) -> None:
    """Register Job Service HTTP routes on the given router."""

    @router.post("/jobs/create")
    async def create_job(request: _CreateJobRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.create_job,
            meta=meta,
            summary=request.summary,
            details=request.details,
            origin_reference=request.origin_reference,
            schedule_type=request.schedule_type,
            timezone=request.timezone,
            definition=request.definition,
            job_action=request.job_action,
            start_state=request.start_state,
        )
        return _to_response(envelope)

    @router.post("/jobs/get")
    async def get_job(request: _JobIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.get_job, meta=meta, job_id=request.job_id
        )
        return _to_response(envelope)

    @router.post("/jobs/list")
    async def list_jobs(request: _ListJobsRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.list_jobs,
            meta=meta,
            state=request.state,
            schedule_type=request.schedule_type,
            limit=request.limit,
            cursor=request.cursor,
        )
        return _to_response(envelope)

    @router.post("/jobs/update")
    async def update_job(request: _UpdateJobRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.update_job,
            meta=meta,
            job_id=request.job_id,
            timezone=request.timezone,
            definition=request.definition,
            notes=request.notes,
        )
        return _to_response(envelope)

    @router.post("/jobs/pause")
    async def pause_job(request: _PauseJobRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.pause_job,
            meta=meta,
            job_id=request.job_id,
            reason=request.reason,
        )
        return _to_response(envelope)

    @router.post("/jobs/resume")
    async def resume_job(request: _JobIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.resume_job, meta=meta, job_id=request.job_id
        )
        return _to_response(envelope)

    @router.post("/jobs/cancel")
    async def cancel_job(request: _JobIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.cancel_job, meta=meta, job_id=request.job_id
        )
        return _to_response(envelope)

    @router.post("/jobs/run-now")
    async def run_job_now(request: _JobIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.run_job_now, meta=meta, job_id=request.job_id
        )
        return _to_response(envelope)

    @router.post("/jobs/executions/get")
    async def get_execution(request: _ExecutionIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.get_execution, meta=meta, execution_id=request.execution_id
        )
        return _to_response(envelope)

    @router.post("/jobs/executions/list")
    async def list_executions(request: _ListExecutionsRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.list_executions,
            meta=meta,
            job_id=request.job_id,
            limit=request.limit,
            cursor=request.cursor,
        )
        return _to_response(envelope)

    @router.post("/jobs/audits/list")
    async def list_job_audits(request: _ListAuditsRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.list_job_audits,
            meta=meta,
            job_id=request.job_id,
            limit=request.limit,
            cursor=request.cursor,
        )
        return _to_response(envelope)

    @router.post("/jobs/predicate-evaluations/list")
    async def list_predicate_evaluations(request: _ListAuditsRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.list_predicate_evaluations,
            meta=meta,
            job_id=request.job_id,
            limit=request.limit,
            cursor=request.cursor,
        )
        return _to_response(envelope)

    @router.post("/jobs/health")
    async def health(request: _MetaFields) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(service.health, meta=meta)
        return _to_response(envelope)

    @router.post("/jobs/executions/claim")
    async def claim_next_execution(request: _ClaimExecutionRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.claim_next_execution,
            meta=meta,
            worker_id=request.worker_id,
        )
        return _to_response(envelope)

    @router.post("/jobs/executions/complete")
    async def complete_execution(request: _ExecutionIdRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.complete_execution,
            meta=meta,
            execution_id=request.execution_id,
        )
        return _to_response(envelope)

    @router.post("/jobs/executions/fail")
    async def fail_execution(request: _FailExecutionRequest) -> _JobResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.fail_execution,
            meta=meta,
            execution_id=request.execution_id,
            error_message=request.error_message,
            error_code=request.error_code,
            is_retryable=request.is_retryable,
        )
        return _to_response(envelope)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta_from(request: _MetaFields) -> EnvelopeMeta:
    """Build EnvelopeMeta from HTTP request fields."""
    return new_meta(
        kind=EnvelopeKind.COMMAND,
        source=request.source,
        principal=request.principal,
        trace_id=request.trace_id,
        parent_id=request.parent_id,
        envelope_id=request.envelope_id,
    )


def _to_response(envelope: Any) -> _JobResponse:
    """Map an Envelope to the HTTP response shape."""
    payload_out: dict[str, Any] | None = None
    if envelope.payload is not None:
        if hasattr(envelope.payload, "model_dump"):
            payload_out = envelope.payload.model_dump(mode="json")
        elif isinstance(envelope.payload, list):
            payload_out = {
                "items": [
                    item.model_dump(mode="json")
                    if hasattr(item, "model_dump")
                    else item
                    for item in envelope.payload
                ]
            }
        else:
            payload_out = {"value": envelope.payload}

    errors_out = [
        _ErrorOut(
            code=e.code,
            message=e.message,
            category=e.category.value
            if isinstance(e.category, ErrorCategory)
            else str(e.category),
            retryable=e.retryable,
            metadata=e.metadata or {},
        )
        for e in (envelope.errors or [])
    ]

    return _JobResponse(payload=payload_out, errors=errors_out)
