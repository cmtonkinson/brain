"""FastAPI route adapters for Relay inbound service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.auth.slash_authenticity import SlashAuthenticityProof
from lib.shared.http.server import read_json_body
from services.effect.relay._inbound.domain import (
    ConsoleEnqueueResult,
    NormalizedOperatorMessage,
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


class _EnqueueConsoleMessageRequest(RequestMeta):
    """Inbound body for console message enqueue requests."""

    message_text: str
    slash_authenticity: SlashAuthenticityProof | None = None


class _PollOperatorInstructionResponse(BaseModel):
    """Serialized response body for operator-instruction dequeue requests."""

    payload: NormalizedOperatorMessage | None
    errors: list[ErrorOut]


class _EnqueueConsoleMessageResponse(BaseModel):
    """Serialized response body for console message enqueue."""

    payload: ConsoleEnqueueResult | None
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
        "/relay/enqueue_console_message",
        response_model=_EnqueueConsoleMessageResponse,
    )
    async def enqueue_console_message(
        request: Request,
    ) -> _EnqueueConsoleMessageResponse:
        """Enqueue one inbound console operator message."""
        body = await read_json_body(request)
        req = _EnqueueConsoleMessageRequest.model_validate(body)
        meta = meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.enqueue_console_message,
            meta=meta,
            message_text=req.message_text,
            slash_authenticity=req.slash_authenticity,
        )
        payload = None if result.payload is None else result.payload.value
        return _EnqueueConsoleMessageResponse(
            payload=payload,
            errors=[error_out(error) for error in result.errors],
        )
