"""FastAPI route adapters for Policy Service approval status."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorDetail
from lib.shared.http.server import read_json_body
from services.reason.policy.domain import ApprovalProposalStatus
from services.reason.policy.service import PolicyService


class _RequestMeta(BaseModel):
    """Common request metadata for Policy HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _ErrorOut(BaseModel):
    """Stable serialized error shape for Policy HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _ApprovalStatusRequest(_RequestMeta):
    """Approval status request body."""

    proposal_token: str


class _ApprovalResponseRequest(_RequestMeta):
    """Approval response request body."""

    proposal_token: str
    intent: str


class _ApprovalStatusResponse(BaseModel):
    """Approval status response body."""

    payload: ApprovalProposalStatus | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: PolicyService) -> None:
    """Register Policy approval routes on one router."""

    @router.post("/policy/approval_status", response_model=_ApprovalStatusResponse)
    async def approval_status(request: Request) -> _ApprovalStatusResponse:
        body = await read_json_body(request)
        req = _ApprovalStatusRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.get_approval_proposal_status,
            meta=meta,
            proposal_token=req.proposal_token,
        )
        payload = None if result.payload is None else result.payload.value
        return _ApprovalStatusResponse(
            payload=payload,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post("/policy/approval_response", response_model=_ApprovalStatusResponse)
    async def approval_response(request: Request) -> _ApprovalStatusResponse:
        body = await read_json_body(request)
        req = _ApprovalResponseRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.record_approval_response,
            meta=meta,
            proposal_token=req.proposal_token,
            intent=req.intent,
        )
        payload = None if result.payload is None else result.payload.value
        return _ApprovalStatusResponse(
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
    """Build command metadata for one inbound Policy HTTP request."""
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


def _error_out(error: ErrorDetail) -> _ErrorOut:
    """Normalize one service error into the Policy HTTP error payload."""
    return _ErrorOut(
        code=error.code,
        message=error.message,
        category=error.category.value,
        retryable=error.retryable,
        metadata=dict(error.metadata) if error.metadata else {},
    )
