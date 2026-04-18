"""FastAPI route adapters for Ingestion Service."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from services.control.ingestion.service import IngestionService


# ---------------------------------------------------------------------------
# Private request / response models
# ---------------------------------------------------------------------------


class _MetaFields(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _SubmitIngestionRequest(_MetaFields):
    source_type: str
    source_uri: str | None = None
    source_actor: str | None = None
    payload_b64: str | None = None
    existing_object_key: str | None = None
    capture_time: str
    mime_type: str | None = None


class _IngestionIdRequest(_MetaFields):
    ingestion_id: str


class _RetryStageRequest(_MetaFields):
    ingestion_id: str
    stage: str


class _ReplayRequest(_MetaFields):
    ingestion_id: str
    from_stage: str


class _ListIngestionRequest(_MetaFields):
    status: str | None = None
    limit: int = 50
    cursor: str | None = None


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _IngestionResponse(BaseModel):
    payload: dict[str, Any] | None
    errors: list[_ErrorOut]


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_routes(*, router: APIRouter, service: IngestionService) -> None:
    """Register Ingestion Service HTTP routes on the given router."""

    @router.post("/ingestion/submit")
    async def submit_ingestion(request: _SubmitIngestionRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        payload_bytes: bytes | None = None
        if request.payload_b64 is not None:
            import base64

            payload_bytes = base64.b64decode(request.payload_b64)
        envelope = await run_in_threadpool(
            service.submit_ingestion,
            meta=meta,
            source_type=request.source_type,
            source_uri=request.source_uri,
            source_actor=request.source_actor,
            payload=payload_bytes,
            existing_object_key=request.existing_object_key,
            capture_time=request.capture_time,
            mime_type=request.mime_type,
        )
        return _to_response(envelope)

    @router.post("/ingestion/get")
    async def get_ingestion(request: _IngestionIdRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.get_ingestion,
            meta=meta,
            ingestion_id=request.ingestion_id,
        )
        return _to_response(envelope)

    @router.post("/ingestion/status")
    async def get_ingestion_status(request: _IngestionIdRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.get_ingestion_status,
            meta=meta,
            ingestion_id=request.ingestion_id,
        )
        return _to_response(envelope)

    @router.post("/ingestion/results")
    async def get_ingestion_results(request: _IngestionIdRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.get_ingestion_results,
            meta=meta,
            ingestion_id=request.ingestion_id,
        )
        return _to_response(envelope)

    @router.post("/ingestion/list")
    async def list_ingestions(request: _ListIngestionRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.list_ingestions,
            meta=meta,
            status=request.status,
            limit=request.limit,
            cursor=request.cursor,
        )
        return _to_response(envelope)

    @router.post("/ingestion/retry-stage")
    async def retry_ingestion_stage(request: _RetryStageRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.retry_ingestion_stage,
            meta=meta,
            ingestion_id=request.ingestion_id,
            stage=request.stage,
        )
        return _to_response(envelope)

    @router.post("/ingestion/replay")
    async def replay_ingestion(request: _ReplayRequest) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(
            service.replay_ingestion,
            meta=meta,
            ingestion_id=request.ingestion_id,
            from_stage=request.from_stage,
        )
        return _to_response(envelope)

    @router.post("/ingestion/health")
    async def health(request: _MetaFields) -> _IngestionResponse:
        meta = _meta_from(request)
        envelope = await run_in_threadpool(service.health, meta=meta)
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


def _to_response(envelope: Any) -> _IngestionResponse:
    """Map an Envelope to the HTTP response shape."""
    payload_out: dict[str, Any] | None = None
    if envelope.payload is not None:
        # envelope.payload is Payload[T] — unwrap to the domain object via .value
        domain_value = envelope.payload.value
        if hasattr(domain_value, "model_dump"):
            payload_out = domain_value.model_dump(mode="json")
        elif isinstance(domain_value, list):
            payload_out = {
                "items": [
                    item.model_dump(mode="json")
                    if hasattr(item, "model_dump")
                    else item
                    for item in domain_value
                ]
            }
        else:
            payload_out = {"value": domain_value}

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

    return _IngestionResponse(payload=payload_out, errors=errors_out)
