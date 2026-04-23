"""FastAPI route adapters for Commitment Service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorCategory
from services.control.commitment.service import CommitmentService


class _MetaFields(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _ExtractCandidatesRequest(_MetaFields):
    text: str
    context: str = ""


class _CreateCommitmentRequest(_MetaFields):
    description: str
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source_context: str | None = None
    due_by: str | None = None
    due_timezone: str | None = None
    importance: int = 2
    effort_provided: int = 2
    effort_inferred: int | None = None
    confidence: float | None = None
    requested_by: str = "operator"


class _UpdateCommitmentRequest(_MetaFields):
    commitment_id: str
    description: str | None = None
    provenance_reference: str | None = None
    ingestion_id: str | None = None
    source_context: str | None = None
    due_by: str | None = None
    due_timezone: str | None = None
    importance: int | None = None
    effort_provided: int | None = None
    effort_inferred: int | None = None
    reviewed_at: str | None = None


class _TransitionCommitmentRequest(_MetaFields):
    commitment_id: str
    to_state: str
    requested_by: str
    reason: str | None = None
    confidence: float | None = None


class _ProgressRequest(_MetaFields):
    commitment_id: str
    provenance_reference: str | None = None
    occurred_at: str
    summary: str
    snippet: str | None = None


class _CommitmentIdRequest(_MetaFields):
    commitment_id: str


class _ListCommitmentsRequest(_MetaFields):
    state: str | None = None
    limit: int = 50
    cursor: str | None = None


class _ReviewRunIdRequest(_MetaFields):
    review_run_id: str


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _Response(BaseModel):
    payload: dict[str, Any] | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: CommitmentService) -> None:
    """Register Commitment Service HTTP routes on the given router."""

    @router.post("/commitment/create")
    async def create_commitment(request: _CreateCommitmentRequest) -> _Response:
        envelope = await run_in_threadpool(
            service.create_commitment,
            meta=_meta_from(request),
            description=request.description,
            provenance_reference=request.provenance_reference,
            ingestion_id=request.ingestion_id,
            source=request.source_context,
            due_by=request.due_by,
            due_timezone=request.due_timezone,
            importance=request.importance,
            effort_provided=request.effort_provided,
            effort_inferred=request.effort_inferred,
            confidence=request.confidence,
            requested_by=request.requested_by,
        )
        return _to_response(envelope)

    @router.post("/commitment/update")
    async def update_commitment(request: _UpdateCommitmentRequest) -> _Response:
        envelope = await run_in_threadpool(
            service.update_commitment,
            meta=_meta_from(request),
            commitment_id=request.commitment_id,
            description=request.description,
            provenance_reference=request.provenance_reference,
            ingestion_id=request.ingestion_id,
            source=request.source_context,
            due_by=request.due_by,
            due_timezone=request.due_timezone,
            importance=request.importance,
            effort_provided=request.effort_provided,
            effort_inferred=request.effort_inferred,
            reviewed_at=request.reviewed_at,
        )
        return _to_response(envelope)

    @router.post("/commitment/transition")
    async def transition_commitment(request: _TransitionCommitmentRequest) -> _Response:
        envelope = await run_in_threadpool(
            service.transition_commitment,
            meta=_meta_from(request),
            commitment_id=request.commitment_id,
            to_state=request.to_state,
            requested_by=request.requested_by,
            reason=request.reason,
            confidence=request.confidence,
        )
        return _to_response(envelope)

    @router.post("/commitment/progress")
    async def record_progress(request: _ProgressRequest) -> _Response:
        envelope = await run_in_threadpool(
            service.record_progress,
            meta=_meta_from(request),
            commitment_id=request.commitment_id,
            provenance_reference=request.provenance_reference,
            occurred_at=request.occurred_at,
            summary=request.summary,
            snippet=request.snippet,
        )
        return _to_response(envelope)

    @router.post("/commitment/get")
    async def get_commitment(request: _CommitmentIdRequest) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.get_commitment,
                meta=_meta_from(request),
                commitment_id=request.commitment_id,
            )
        )

    @router.post("/commitment/list")
    async def list_commitments(request: _ListCommitmentsRequest) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.list_commitments,
                meta=_meta_from(request),
                state=request.state,
                limit=request.limit,
                cursor=request.cursor,
            )
        )

    @router.post("/commitment/history")
    async def get_history(request: _CommitmentIdRequest) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.get_commitment_history,
                meta=_meta_from(request),
                commitment_id=request.commitment_id,
            )
        )

    @router.post("/commitment/review-run")
    async def get_review_run(request: _ReviewRunIdRequest) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.get_review_run,
                meta=_meta_from(request),
                review_run_id=request.review_run_id,
            )
        )

    @router.post("/commitment/review-items")
    async def get_review_items(request: _ReviewRunIdRequest) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.list_review_items,
                meta=_meta_from(request),
                review_run_id=request.review_run_id,
            )
        )

    @router.post("/commitment/extract-candidates")
    async def extract_commitment_candidates(
        request: _ExtractCandidatesRequest,
    ) -> _Response:
        return _to_response(
            await run_in_threadpool(
                service.extract_commitment_candidates,
                meta=_meta_from(request),
                text=request.text,
                context=request.context,
            )
        )

    @router.post("/commitment/health")
    async def health(request: _MetaFields) -> _Response:
        return _to_response(
            await run_in_threadpool(service.health, meta=_meta_from(request))
        )


def _meta_from(request: _MetaFields) -> EnvelopeMeta:
    return new_meta(
        kind=EnvelopeKind.COMMAND,
        source=request.source,
        principal=request.principal,
        trace_id=request.trace_id,
        parent_id=request.parent_id,
        envelope_id=request.envelope_id,
    )


def _to_response(envelope: Any) -> _Response:
    payload_out: dict[str, Any] | None = None
    if envelope.payload is not None:
        value = envelope.payload.value
        if hasattr(value, "model_dump"):
            payload_out = value.model_dump(mode="json")
        elif isinstance(value, (list, tuple)):
            payload_out = {
                "items": [
                    item.model_dump(mode="json")
                    if hasattr(item, "model_dump")
                    else item
                    for item in value
                ]
            }
        else:
            payload_out = {"value": value}
    errors_out = [
        _ErrorOut(
            code=error.code,
            message=error.message,
            category=error.category.value
            if isinstance(error.category, ErrorCategory)
            else str(error.category),
            retryable=error.retryable,
            metadata=error.metadata or {},
        )
        for error in (envelope.errors or [])
    ]
    return _Response(payload=payload_out, errors=errors_out)
