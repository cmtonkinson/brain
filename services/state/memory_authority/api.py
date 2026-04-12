"""FastAPI route adapters for Memory Authority Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http.server import read_json_body
from services.state.memory_authority.domain import (
    ContextBlock,
    InboundInstructionRecord,
    TurnRecord,
)
from services.state.memory_authority.service import MemoryAuthorityService


class _RequestMeta(BaseModel):
    """Shared inbound request metadata for MAS HTTP routes."""

    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _RecordInboundTurnRequest(_RequestMeta):
    """Inbound body for MAS inbound-turn recording requests."""

    session_id: str
    message: str
    instruction: "_InboundInstructionRequest | None" = None


class _InboundInstructionRequest(BaseModel):
    """Serialized inbound instruction metadata for MAS turn recording."""

    sender_e164: str
    message_text: str
    timestamp_ms: int
    source_device: str
    source: str
    group_id: str | None = None
    quote_target_timestamp_ms: int | None = None
    reaction_target_timestamp_ms: int | None = None
    reaction_emoji: str | None = None
    approval_intent: str | None = None
    reply_to_proposal_token: str | None = None
    reaction_to_proposal_token: str | None = None


class _AssembleSnapshotRequest(_RequestMeta):
    """Inbound body for MAS snapshot assembly requests."""

    session_id: str


class _RecordOutboundCandidateRequest(_RequestMeta):
    """Inbound body for MAS outbound-candidate recording requests."""

    session_id: str
    content: str
    model: str
    provider: str
    token_count: int
    reasoning_level: str


class _RecordResponseRequest(_RecordOutboundCandidateRequest):
    """Inbound body for backward-compatible record-response requests."""


class _RecordOutboundDeliveryRequest(_RequestMeta):
    """Inbound body for MAS outbound-delivery recording requests."""

    session_id: str
    turn_id: str
    delivered: bool


class _ErrorOut(BaseModel):
    """Stable serialized error shape for MAS HTTP responses."""

    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _AssembleContextResponse(BaseModel):
    """Serialized response body for MAS assemble-context."""

    payload: ContextBlock | None
    errors: list[_ErrorOut]


class _TurnResponse(BaseModel):
    """Serialized response body for MAS turn-record operations."""

    payload: TurnRecord | None
    errors: list[_ErrorOut]


class _BoolResponse(BaseModel):
    """Serialized response body for MAS boolean turn state operations."""

    payload: bool | None
    errors: list[_ErrorOut]


class _CreateSessionRequest(_RequestMeta):
    """Inbound body for MAS create-session requests."""

    system_prompt: str


class _CreateSessionResponse(BaseModel):
    """Serialized response body for MAS create-session."""

    session_id: str | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: MemoryAuthorityService) -> None:
    """Register Memory Authority routes on one router."""

    @router.post(
        "/memory/create_session",
        response_model=_CreateSessionResponse,
    )
    async def create_session(request: Request) -> _CreateSessionResponse:
        """Create one MAS session and return only the session identifier."""
        body = await read_json_body(request)
        req = _CreateSessionRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.create_session, meta=meta, system_prompt=req.system_prompt
        )
        session_id = None
        if result.payload is not None:
            session_id = result.payload.value.id
        return _CreateSessionResponse(
            session_id=session_id,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/get_latest_or_create_session",
        response_model=_CreateSessionResponse,
    )
    async def get_latest_or_create_session(request: Request) -> _CreateSessionResponse:
        """Return the latest MAS session id or create one when none exist."""
        body = await read_json_body(request)
        req = _RequestMeta.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.get_latest_or_create_session,
            meta=meta,
        )
        session_id = None
        if result.payload is not None:
            session_id = result.payload.value.id
        return _CreateSessionResponse(
            session_id=session_id,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/assemble_context",
        response_model=_AssembleContextResponse,
    )
    async def assemble_context(request: Request) -> _AssembleContextResponse:
        """Append one inbound message and return the assembled MAS context block."""
        body = await read_json_body(request)
        req = _RecordInboundTurnRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        inbound = await run_in_threadpool(
            service.record_inbound_turn,
            meta=meta,
            session_id=req.session_id,
            message=req.message,
            instruction=(
                None
                if req.instruction is None
                else InboundInstructionRecord(**req.instruction.model_dump())
            ),
        )
        if inbound.payload is None:
            return _AssembleContextResponse(
                payload=None,
                errors=[_error_out(error) for error in inbound.errors],
            )
        snapshot = await run_in_threadpool(
            service.assemble_snapshot,
            meta=meta,
            session_id=req.session_id,
        )
        payload = None if snapshot.payload is None else snapshot.payload.value
        return _AssembleContextResponse(
            payload=payload,
            errors=[_error_out(error) for error in snapshot.errors],
        )

    @router.post(
        "/memory/record_inbound_turn",
        response_model=_TurnResponse,
    )
    async def record_inbound_turn(request: Request) -> _TurnResponse:
        """Persist one inbound turn and return the authoritative turn record."""
        body = await read_json_body(request)
        req = _RecordInboundTurnRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.record_inbound_turn,
            meta=meta,
            session_id=req.session_id,
            message=req.message,
            instruction=(
                None
                if req.instruction is None
                else InboundInstructionRecord(**req.instruction.model_dump())
            ),
        )
        payload = None if result.payload is None else result.payload.value
        return _TurnResponse(
            payload=payload,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/assemble_snapshot",
        response_model=_AssembleContextResponse,
    )
    async def assemble_snapshot(request: Request) -> _AssembleContextResponse:
        """Return the historical MAS context snapshot without the live turn."""
        body = await read_json_body(request)
        req = _AssembleSnapshotRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.assemble_snapshot,
            meta=meta,
            session_id=req.session_id,
        )
        payload = None if result.payload is None else result.payload.value
        return _AssembleContextResponse(
            payload=payload,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/record_outbound_candidate",
        response_model=_TurnResponse,
    )
    async def record_outbound_candidate(request: Request) -> _TurnResponse:
        """Persist one outbound candidate turn and return the authoritative row."""
        body = await read_json_body(request)
        req = _RecordOutboundCandidateRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.record_outbound_candidate,
            meta=meta,
            session_id=req.session_id,
            content=req.content,
            model=req.model,
            provider=req.provider,
            token_count=req.token_count,
            reasoning_level=req.reasoning_level,
        )
        payload = None if result.payload is None else result.payload.value
        return _TurnResponse(
            payload=payload,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/record_outbound_delivery",
        response_model=_BoolResponse,
    )
    async def record_outbound_delivery(request: Request) -> _BoolResponse:
        """Persist one outbound delivery result."""
        body = await read_json_body(request)
        req = _RecordOutboundDeliveryRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.record_outbound_delivery,
            meta=meta,
            session_id=req.session_id,
            turn_id=req.turn_id,
            delivered=req.delivered,
        )
        payload = None if result.payload is None else result.payload.value
        return _BoolResponse(
            payload=payload,
            errors=[_error_out(error) for error in result.errors],
        )

    @router.post(
        "/memory/record_response",
        response_model=_BoolResponse,
    )
    async def record_response(request: Request) -> _BoolResponse:
        """Append one outbound response turn with response metadata."""
        body = await read_json_body(request)
        req = _RecordResponseRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.record_response,
            meta=meta,
            session_id=req.session_id,
            content=req.content,
            model=req.model,
            provider=req.provider,
            token_count=req.token_count,
            reasoning_level=req.reasoning_level,
        )
        payload = None if result.payload is None else result.payload.value
        return _BoolResponse(
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
    """Build command metadata for one inbound MAS HTTP request."""
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
