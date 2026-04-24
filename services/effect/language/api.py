"""FastAPI route adapters for Language Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorDetail
from lib.shared.http.server import read_json_body
from lib.shared.language_model import InferenceRequest
from services.effect.language.service import LanguageService
from services.effect.language.validation import ReasoningLevel


class _ChatRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    system_prompt: str = ""
    prompt: str
    profile: ReasoningLevel = ReasoningLevel.STANDARD


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _ChatPayload(BaseModel):
    text: str
    provider: str
    model: str


class _ChatResponse(BaseModel):
    payload: _ChatPayload | None
    errors: list[_ErrorOut]


class _ToolCall(BaseModel):
    tool_name: str
    args_json: str
    tool_call_id: str


class _ChatWithToolsRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    inference_request: InferenceRequest


class _ChatWithToolsPayload(BaseModel):
    provider: str
    model: str
    finish_reason: str
    text: str | None = None
    tool_calls: tuple[_ToolCall, ...] = ()


class _ChatWithToolsResponse(BaseModel):
    payload: _ChatWithToolsPayload | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: LanguageService) -> None:
    """Register Language Service routes on one router."""

    @router.post("/lms/chat", response_model=_ChatResponse)
    async def language_chat(request: Request) -> _ChatResponse:
        body = await read_json_body(request)
        req = _ChatRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.chat,
            meta=meta,
            system_prompt=req.system_prompt,
            prompt=req.prompt,
            profile=req.profile,
        )
        payload = None
        if result.payload is not None:
            p = result.payload.value
            payload = _ChatPayload(text=p.text, provider=p.provider, model=p.model)
        return _ChatResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/lms/chat-with-tools", response_model=_ChatWithToolsResponse)
    async def language_chat_with_tools(request: Request) -> _ChatWithToolsResponse:
        body = await read_json_body(request)
        req = _ChatWithToolsRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.chat_with_tools,
            meta=meta,
            inference_request=req.inference_request,
        )
        payload = None
        if result.payload is not None:
            p = result.payload.value
            payload = _ChatWithToolsPayload(
                provider=p.provider,
                model=p.model,
                finish_reason=p.finish_reason,
                text=p.text,
                tool_calls=tuple(
                    _ToolCall.model_validate(item.model_dump(mode="python"))
                    for item in p.tool_calls
                ),
            )
        return _ChatWithToolsResponse(
            payload=payload,
            errors=[_error_out(e) for e in result.errors],
        )


def _meta_from_request(
    source: str,
    principal: str,
    trace_id: str | None,
    parent_id: str,
    envelope_id: str | None,
) -> EnvelopeMeta:
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
    return _ErrorOut(
        code=error.code,
        message=error.message,
        category=error.category.value,
        retryable=error.retryable,
        metadata=dict(error.metadata) if error.metadata else {},
    )
