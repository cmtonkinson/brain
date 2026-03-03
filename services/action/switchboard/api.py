"""FastAPI route adapters for Switchboard Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http.server import read_json_body
from services.action.switchboard.domain import NormalizedSignalMessage
from services.action.switchboard.service import SwitchboardService


class _RequestMeta(BaseModel):
    """Shared inbound request metadata for Switchboard HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _PollOperatorInstructionRequest(_RequestMeta):
    """Inbound body for operator-instruction dequeue requests."""

    wait_timeout_seconds: float = 0.0


class _ErrorOut(BaseModel):
    """Stable serialized error shape for Switchboard HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _PollOperatorInstructionResponse(BaseModel):
    """Serialized response body for operator-instruction dequeue requests."""

    payload: NormalizedSignalMessage | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: SwitchboardService) -> None:
    """Register Switchboard routes on one router."""

    @router.post(
        "/switchboard/poll_operator_instruction",
        response_model=_PollOperatorInstructionResponse,
    )
    async def poll_operator_instruction(
        request: Request,
    ) -> _PollOperatorInstructionResponse:
        """Pop the next queued operator instruction, optionally long-polling."""
        body = await read_json_body(request)
        req = _PollOperatorInstructionRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = service.poll_operator_instruction(
            meta=meta,
            wait_timeout_seconds=req.wait_timeout_seconds,
        )
        payload = None if result.payload is None else result.payload.value
        return _PollOperatorInstructionResponse(
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
    """Build command metadata for one inbound Switchboard HTTP request."""
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
