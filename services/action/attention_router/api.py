"""FastAPI route adapters for Attention Router Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorCategory
from lib.shared.http.server import read_json_body
from services.action.attention_router.domain import ConsoleResponseMessage
from services.action.attention_router.service import AttentionRouterService


class _RequestMeta(BaseModel):
    """Shared inbound request metadata for Attention Router HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _PollConsoleResponseRequest(_RequestMeta):
    """Inbound body for console response dequeue requests."""

    wait_timeout_seconds: float = 0.0


class _ErrorOut(BaseModel):
    """Stable serialized error shape for Attention Router HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _PollConsoleResponseResponse(BaseModel):
    """Serialized response body for console response dequeue requests."""

    payload: ConsoleResponseMessage | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: AttentionRouterService) -> None:
    """Register Attention Router routes on one router."""

    @router.post(
        "/attention-router/poll_console_response",
        response_model=_PollConsoleResponseResponse,
    )
    async def poll_console_response(
        request: Request,
    ) -> _PollConsoleResponseResponse:
        """Pop the next queued Brain response for the console channel."""
        body = await read_json_body(request)
        req = _PollConsoleResponseRequest.model_validate(body)
        meta = _meta_from_request(
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
            errors=[_error_out(error) for error in result.errors],
        )


def _meta_from_request(
    source: str,
    principal: str,
    trace_id: str | None,
    parent_id: str,
    envelope_id: str | None,
) -> EnvelopeMeta:
    """Build command metadata for one inbound Attention Router HTTP request."""
    meta = new_meta(
        kind=EnvelopeKind.COMMAND,
        source=source,
        principal=principal,
    )
    return EnvelopeMeta(
        envelope_id=envelope_id or meta.envelope_id,
        trace_id=trace_id or meta.trace_id,
        parent_id=parent_id,
        kind=EnvelopeKind.COMMAND,
        timestamp=meta.timestamp,
        source=source,
        principal=principal,
    )


def _error_out(error: object) -> _ErrorOut:
    """Normalize one service error into the shared HTTP error payload."""
    category_map = {
        ErrorCategory.VALIDATION: "validation",
        ErrorCategory.CONFLICT: "conflict",
        ErrorCategory.NOT_FOUND: "not_found",
        ErrorCategory.POLICY: "policy",
        ErrorCategory.DEPENDENCY: "dependency",
        ErrorCategory.INTERNAL: "internal",
    }
    return _ErrorOut(
        code=str(getattr(error, "code", "")),
        message=str(getattr(error, "message", "")),
        category=category_map.get(getattr(error, "category", None), "unspecified"),
        retryable=bool(getattr(error, "retryable", False)),
        metadata=dict(getattr(error, "metadata", {})),
    )
