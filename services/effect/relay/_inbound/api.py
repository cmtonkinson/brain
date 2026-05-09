"""FastAPI route adapters for Relay inbound service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.http.server import read_json_body
from lib.shared.inbound_message import InboundMessage
from services.effect.relay._inbound.domain import (
    IngestResult,
)
from services.effect.relay._inbound.service import RelayInboundService
from services.effect.relay._shared import (
    ErrorOut,
    RequestMeta,
    error_out,
    meta_from_request,
)


class _PollOperatorInstructionRequest(RequestMeta):
    """Inbound body for operator-instruction dequeue requests."""

    wait_timeout_seconds: float = 0.0


class _IngestInboundMessageRequest(RequestMeta):
    """Inbound body for normalized message ingestion."""

    message: InboundMessage


class _PollOperatorInstructionResponse(BaseModel):
    """Serialized response body for operator-instruction dequeue requests."""

    payload: InboundMessage | None
    errors: list[ErrorOut]


class _IngestInboundMessageResponse(BaseModel):
    """Serialized response body for normalized message ingestion."""

    payload: IngestResult | None
    errors: list[ErrorOut]


def register_routes(*, router: APIRouter, service: RelayInboundService) -> None:
    """Register Relay inbound routes on one router."""

    @router.post(
        "/relay/poll_operator_instruction",
        response_model=_PollOperatorInstructionResponse,
    )
    async def poll_operator_instruction(
        request: Request,
    ) -> _PollOperatorInstructionResponse:
        """Pop the next queued operator instruction, optionally long-polling."""
        body = await read_json_body(request)
        req = _PollOperatorInstructionRequest.model_validate(body)
        meta = meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.poll_operator_instruction,
            meta=meta,
            wait_timeout_seconds=req.wait_timeout_seconds,
        )
        payload = None if result.payload is None else result.payload.value
        return _PollOperatorInstructionResponse(
            payload=payload,
            errors=[error_out(error) for error in result.errors],
        )

    @router.post(
        "/relay/ingest_inbound_message",
        response_model=_IngestInboundMessageResponse,
    )
    async def ingest_inbound_message(
        request: Request,
    ) -> _IngestInboundMessageResponse:
        """Ingest one already-normalized inbound operator message."""
        body = await read_json_body(request)
        req = _IngestInboundMessageRequest.model_validate(body)
        meta = meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.ingest_inbound_message,
            meta=meta,
            message=req.message,
        )
        payload = None if result.payload is None else result.payload.value
        return _IngestInboundMessageResponse(
            payload=payload,
            errors=[error_out(error) for error in result.errors],
        )
