"""FastAPI route adapters for Language Model Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http.server import read_json_body
from services.action.language_model.domain import (
    ChatMessage,
    ChatToolDefinition,
)
from services.action.language_model.service import LanguageModelService
from services.action.language_model.validation import ReasoningLevel


class _ChatRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    prompt: str
    profile: str = "standard"


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


class _ToolDefinition(BaseModel):
    name: str
    parameters_json_schema: dict[str, object]
    description: str | None = None
    strict: bool | None = None
    sequential: bool = False


class _ToolCall(BaseModel):
    tool_name: str
    args_json: str
    tool_call_id: str


class _ChatMessage(BaseModel):
    role: str
    content: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_calls: tuple[_ToolCall, ...] = ()


class _ChatWithToolsRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    messages: tuple[_ChatMessage, ...]
    tools: tuple[_ToolDefinition, ...] = ()
    tool_choice: str | dict[str, object] | None = None
    parallel_tool_calls: bool | None = None
    allow_text_output: bool = True
    profile: str = "standard"


class _ChatWithToolsPayload(BaseModel):
    provider: str
    model: str
    finish_reason: str
    text: str | None = None
    tool_calls: tuple[_ToolCall, ...] = ()


class _ChatWithToolsResponse(BaseModel):
    payload: _ChatWithToolsPayload | None
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: LanguageModelService) -> None:
    """Register Language Model Service routes on one router."""

    @router.post("/lms/chat", response_model=_ChatResponse)
    async def lms_chat(request: Request) -> _ChatResponse:
        body = await read_json_body(request)
        req = _ChatRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        profile = _resolve_profile(req.profile)
        result = await run_in_threadpool(
            service.chat,
            meta=meta,
            prompt=req.prompt,
            profile=profile,
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
    async def lms_chat_with_tools(request: Request) -> _ChatWithToolsResponse:
        body = await read_json_body(request)
        req = _ChatWithToolsRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        profile = _resolve_profile(req.profile)
        result = await run_in_threadpool(
            service.chat_with_tools,
            meta=meta,
            messages=[
                ChatMessage.model_validate(item.model_dump(mode="python"))
                for item in req.messages
            ],
            tools=[
                ChatToolDefinition.model_validate(item.model_dump(mode="python"))
                for item in req.tools
            ],
            tool_choice=req.tool_choice,
            parallel_tool_calls=req.parallel_tool_calls,
            allow_text_output=req.allow_text_output,
            profile=profile,
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


def _resolve_profile(profile: str) -> ReasoningLevel:
    """Map profile string to ReasoningLevel, defaulting to standard."""
    try:
        return ReasoningLevel(profile.strip().lower())
    except ValueError:
        return ReasoningLevel.STANDARD


def _error_out(error: object) -> _ErrorOut:
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
