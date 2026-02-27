"""FastAPI route adapters for Language Model Service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http.server import read_json_body
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
        result = service.chat(meta=meta, prompt=req.prompt, profile=profile)
        payload = None
        if result.payload is not None:
            p = result.payload.value
            payload = _ChatPayload(text=p.text, provider=p.provider, model=p.model)
        return _ChatResponse(
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
