"""FastAPI route adapters for Delegation Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorCategory
from lib.shared.http.server import read_json_body
from services.reason.delegation.domain import (
    CancelOutcome,
    CancelReason,
    ClaimedInvocation,
    InvocationResult,
    InvocationStarted,
    InvocationStatus,
    InvocationStatusView,
    TurnDecision,
)
from services.reason.delegation.service import DelegationService


class _RequestMeta(BaseModel):
    """Shared inbound request metadata for Delegation HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _InvokeRequest(_RequestMeta):
    """Inbound body for Delegation invoke and invoke-and-wait routes."""

    prompt: str
    context_text: str | None = None
    context_object_refs: list[str] = []
    personality_id: str = "subagent"
    tool_allowlist: list[str] | None = None
    max_turns: int = 8
    budget_tokens: int | None = None
    max_wallclock_seconds: int | None = None
    parent_invocation_id: str | None = None
    timeout_seconds: float | None = None


class _InvocationIdRequest(_RequestMeta):
    """Inbound body identifying one invocation."""

    invocation_id: str


class _WaitRequest(_InvocationIdRequest):
    """Inbound body for the Delegation wait route."""

    timeout_seconds: float | None = None


class _CancelRequest(_InvocationIdRequest):
    """Inbound body for the Delegation cancel route."""

    reason: str = "manual"


class _ClaimRequest(_RequestMeta):
    """Inbound body for the Delegation claim route."""

    claimed_by: str = "subagent"


class _RecordTurnRequest(_InvocationIdRequest):
    """Inbound body for the Delegation record-turn route."""


class _FinalizeRequest(_InvocationIdRequest):
    """Inbound body for the Delegation finalize route."""

    status: str
    final_response: str | None = None
    transcript_ref: str | None = None
    cancel_reason: str | None = None


class _ErrorOut(BaseModel):
    """Stable serialized error shape for Delegation HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _StartedResponse(BaseModel):
    """Serialized response body for invoke."""

    payload: InvocationStarted | None
    errors: list[_ErrorOut]


class _ResultResponse(BaseModel):
    """Serialized response body for invoke-and-wait, wait, finalize."""

    payload: InvocationResult | None
    errors: list[_ErrorOut]


class _StatusResponse(BaseModel):
    """Serialized response body for status."""

    payload: InvocationStatusView | None
    errors: list[_ErrorOut]


class _CancelResponse(BaseModel):
    """Serialized response body for cancel."""

    payload: CancelOutcome | None
    errors: list[_ErrorOut]


class _ClaimResponse(BaseModel):
    """Serialized response body for claim."""

    payload: ClaimedInvocation | None
    errors: list[_ErrorOut]


class _TurnDecisionResponse(BaseModel):
    """Serialized response body for record-turn."""

    payload: TurnDecision | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: DelegationService) -> None:
    """Register Delegation routes on one router."""

    @router.post("/delegation/invoke", response_model=_StartedResponse)
    async def invoke(request: Request) -> _StartedResponse:
        """Queue one delegated invocation and return its identifier."""
        body = await read_json_body(request)
        req = _InvokeRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.invoke,
            meta=meta,
            **_invoke_kwargs(req),
        )
        payload = None if result.payload is None else result.payload.value
        return _StartedResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/invoke-and-wait", response_model=_ResultResponse)
    async def invoke_and_wait(request: Request) -> _ResultResponse:
        """Queue one delegated invocation and block until terminal state."""
        body = await read_json_body(request)
        req = _InvokeRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.invoke_and_wait,
            meta=meta,
            **_invoke_kwargs(req),
            timeout_seconds=req.timeout_seconds,
        )
        payload = None if result.payload is None else result.payload.value
        return _ResultResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/wait", response_model=_ResultResponse)
    async def wait(request: Request) -> _ResultResponse:
        """Block until a previously queued invocation reaches terminal state."""
        body = await read_json_body(request)
        req = _WaitRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.wait,
            meta=meta,
            invocation_id=req.invocation_id,
            timeout_seconds=req.timeout_seconds,
        )
        payload = None if result.payload is None else result.payload.value
        return _ResultResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/status", response_model=_StatusResponse)
    async def get_status(request: Request) -> _StatusResponse:
        """Return the current status projection for one invocation."""
        body = await read_json_body(request)
        req = _InvocationIdRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.get_status,
            meta=meta,
            invocation_id=req.invocation_id,
        )
        payload = None if result.payload is None else result.payload.value
        return _StatusResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/cancel", response_model=_CancelResponse)
    async def cancel(request: Request) -> _CancelResponse:
        """Request cancellation of a queued or running invocation."""
        body = await read_json_body(request)
        req = _CancelRequest.model_validate(body)
        meta = _meta_from_request(req)
        try:
            cancel_reason = CancelReason(req.reason)
        except ValueError:
            cancel_reason = CancelReason.manual
        result = await run_in_threadpool(
            service.cancel,
            meta=meta,
            invocation_id=req.invocation_id,
            reason=cancel_reason,
        )
        payload = None if result.payload is None else result.payload.value
        return _CancelResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/claim", response_model=_ClaimResponse)
    async def claim(request: Request) -> _ClaimResponse:
        """Claim the oldest queued invocation for a Subagent Actor."""
        body = await read_json_body(request)
        req = _ClaimRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.claim_next_invocation,
            meta=meta,
            claimed_by=req.claimed_by,
        )
        payload = None if result.payload is None else result.payload.value
        return _ClaimResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/record-turn", response_model=_TurnDecisionResponse)
    async def record_turn(request: Request) -> _TurnDecisionResponse:
        """Bump turn count and re-evaluate budget for one invocation."""
        body = await read_json_body(request)
        req = _RecordTurnRequest.model_validate(body)
        meta = _meta_from_request(req)
        result = await run_in_threadpool(
            service.record_turn,
            meta=meta,
            invocation_id=req.invocation_id,
        )
        payload = None if result.payload is None else result.payload.value
        return _TurnDecisionResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/delegation/finalize", response_model=_ResultResponse)
    async def finalize(request: Request) -> _ResultResponse:
        """Apply terminal status to one invocation row."""
        body = await read_json_body(request)
        req = _FinalizeRequest.model_validate(body)
        meta = _meta_from_request(req)
        try:
            status = InvocationStatus(req.status)
        except ValueError:
            return _ResultResponse(
                payload=None,
                errors=[
                    _ErrorOut(
                        code="VALIDATION_ERROR",
                        message=f"unknown status: {req.status}",
                        category="validation",
                        retryable=False,
                        metadata={},
                    )
                ],
            )
        cancel_reason: CancelReason | None = None
        if req.cancel_reason is not None:
            try:
                cancel_reason = CancelReason(req.cancel_reason)
            except ValueError:
                cancel_reason = None
        result = await run_in_threadpool(
            service.finalize_invocation,
            meta=meta,
            invocation_id=req.invocation_id,
            status=status,
            final_response=req.final_response,
            transcript_ref=req.transcript_ref,
            cancel_reason=cancel_reason,
        )
        payload = None if result.payload is None else result.payload.value
        return _ResultResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )


def _meta_from_request(req: _RequestMeta) -> EnvelopeMeta:
    """Build command metadata for one inbound Delegation HTTP request."""
    base = new_meta(
        kind=EnvelopeKind.COMMAND,
        source=req.source,
        principal=req.principal,
    )
    return EnvelopeMeta(
        envelope_id=req.envelope_id or base.envelope_id,
        trace_id=req.trace_id or base.trace_id,
        parent_id=req.parent_id,
        kind=EnvelopeKind.COMMAND,
        timestamp=base.timestamp,
        source=req.source,
        principal=req.principal,
    )


def _invoke_kwargs(req: _InvokeRequest) -> dict[str, object]:
    """Project HTTP body into the flat kwargs used by the service invoke API."""
    return {
        "prompt": req.prompt,
        "context_text": req.context_text,
        "context_object_refs": tuple(req.context_object_refs),
        "personality_id": req.personality_id,
        "tool_allowlist": (
            None if req.tool_allowlist is None else tuple(req.tool_allowlist)
        ),
        "max_turns": req.max_turns,
        "budget_tokens": req.budget_tokens,
        "max_wallclock_seconds": req.max_wallclock_seconds,
        "parent_invocation_id": req.parent_invocation_id,
    }


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
