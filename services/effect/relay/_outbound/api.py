"""FastAPI route adapters for Relay outbound service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.http.server import read_json_body
from services.effect.relay._outbound.domain import ConsoleResponseMessage
from services.effect.relay._outbound.service import RelayOutboundService
from services.effect.relay._shared import (
    ErrorOut,
    RequestMeta,
    error_out,
    meta_from_request,
)


class _PollConsoleResponseRequest(RequestMeta):
    """Inbound body for console response dequeue requests."""

    wait_timeout_seconds: float = 0.0


class _PollConsoleResponseResponse(BaseModel):
    """Serialized response body for console response dequeue requests."""

    payload: ConsoleResponseMessage | None
    errors: list[ErrorOut]


def register_routes(*, router: APIRouter, service: RelayOutboundService) -> None:
    """Register Relay outbound routes on one router."""

    @router.post(
        "/relay/poll_console_response",
        response_model=_PollConsoleResponseResponse,
    )
    async def poll_console_response(
        request: Request,
    ) -> _PollConsoleResponseResponse:
        """Pop the next queued Brain response for the console channel."""
        body = await read_json_body(request)
        req = _PollConsoleResponseRequest.model_validate(body)
        meta = meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.poll_console_response,
            meta=meta,
            wait_timeout_seconds=req.wait_timeout_seconds,
        )
        payload = None if result.payload is None else result.payload.value
        return _PollConsoleResponseResponse(
            payload=payload,
            errors=[error_out(error) for error in result.errors],
        )
