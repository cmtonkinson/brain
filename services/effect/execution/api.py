"""FastAPI route adapters for Execution Service."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from lib.shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from lib.shared.errors import ErrorDetail
from lib.shared.http.server import read_json_body
from services.effect.execution.domain import (
    DynamicOpClassificationRow,
    OpDescriptor,
    OpInvocationMetadata,
    OpInvokeResult,
    OpSearchHit,
    ToolSystemHint,
)
from services.effect.execution.service import ExecutionService


class _DescribeRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _OpDescriptorOut(BaseModel):
    op_id: str
    kind: str
    version: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    simple_output_path: str | None
    effect: str
    approval: str
    required_ops: tuple[str, ...]
    slash_command_name: str | None = None
    slash_command_aliases: tuple[str, ...] = ()
    slash_command_description: str | None = None


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _DescribeResponse(BaseModel):
    ops: list[_OpDescriptorOut]
    errors: list[_ErrorOut]


class _SearchRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    query: str
    limit: int | None = None


class _DescribeOneRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    op_id: str


class _SlashLookupRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    name: str


class _SlashLookupResponse(BaseModel):
    op: _OpDescriptorOut | None
    errors: list[_ErrorOut]


class _OpSearchHitOut(BaseModel):
    op_id: str
    required_params: list[str]
    summary: str


class _SearchResponse(BaseModel):
    results: list[_OpSearchHitOut]
    errors: list[_ErrorOut]


class _ToolSystemHintOut(BaseModel):
    system_id: str
    label: str
    summary: str
    kind: str
    ready: bool | None = None
    tool_count: int | None = None
    pending_tool_count: int | None = None


class _ToolSystemHintsResponse(BaseModel):
    systems: list[_ToolSystemHintOut]
    errors: list[_ErrorOut]


class _DescribeOneResponse(BaseModel):
    op: _OpDescriptorOut | None
    errors: list[_ErrorOut]


class _DynamicOpClassificationOut(BaseModel):
    op_id: str
    source_kind: str
    source_ref: str
    definition_digest: str
    summary: str
    input_schema: dict[str, Any] | None
    output_schema: dict[str, Any] | None
    effect: str | None
    approval: str | None


class _DynamicOpClassificationListResponse(BaseModel):
    items: list[_DynamicOpClassificationOut]
    errors: list[_ErrorOut]


class _DynamicOpClassificationRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    op_id: str
    effect: str | None = None
    approval: str | None = None


class _PolicyDecision(BaseModel):
    decision_id: str
    allowed: bool
    reason_codes: list[str]
    obligations: list[str]
    proposal_id: str


class _InvokeRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""
    op_id: str
    input_payload: dict[str, Any] = {}
    actor: str = ""
    channel: str = ""
    invocation_id: str = ""
    parent_invocation_id: str = ""
    confirmed: bool = False
    approval_token: str = ""
    reply_to_proposal_token: str = ""
    reaction_to_proposal_token: str = ""


class _InvokeResponse(BaseModel):
    output_json: str
    policy: _PolicyDecision
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: ExecutionService) -> None:
    """Register Execution routes on one router."""

    @router.post("/ops/describe", response_model=_DescribeResponse)
    async def describe_ops(request: Request) -> _DescribeResponse:
        body = await read_json_body(request)
        req = _DescribeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(service.describe_ops, meta=meta)
        ops = (
            []
            if result.payload is None
            else [_descriptor_out(item) for item in result.payload.value]
        )
        return _DescribeResponse(
            ops=ops,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/always-on", response_model=_DescribeResponse)
    async def list_always_on_ops(request: Request) -> _DescribeResponse:
        body = await read_json_body(request)
        req = _DescribeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(service.list_always_on_ops, meta=meta)
        ops = (
            []
            if result.payload is None
            else [_descriptor_out(item) for item in result.payload.value]
        )
        return _DescribeResponse(
            ops=ops,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/search", response_model=_SearchResponse)
    async def search_ops(request: Request) -> _SearchResponse:
        body = await read_json_body(request)
        req = _SearchRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.search_ops,
            meta=meta,
            query=req.query,
            limit=req.limit,
        )
        hits = (
            []
            if result.payload is None
            else [_search_hit_out(item) for item in result.payload.value]
        )
        return _SearchResponse(
            results=hits,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/tool-system-hints", response_model=_ToolSystemHintsResponse)
    async def list_tool_system_hints(request: Request) -> _ToolSystemHintsResponse:
        body = await read_json_body(request)
        req = _DescribeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(service.list_tool_system_hints, meta=meta)
        systems = (
            []
            if result.payload is None
            else [_tool_system_hint_out(item) for item in result.payload.value]
        )
        return _ToolSystemHintsResponse(
            systems=systems,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/describe-one", response_model=_DescribeOneResponse)
    async def describe_op(request: Request) -> _DescribeOneResponse:
        body = await read_json_body(request)
        req = _DescribeOneRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.describe_op,
            meta=meta,
            op_id=req.op_id,
        )
        op = None if result.payload is None else _descriptor_out(result.payload.value)
        return _DescribeOneResponse(
            op=op,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/slash-lookup", response_model=_SlashLookupResponse)
    async def slash_lookup(request: Request) -> _SlashLookupResponse:
        body = await read_json_body(request)
        req = _SlashLookupRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.resolve_slash_command,
            meta=meta,
            name=req.name,
        )
        op = (
            None
            if result.payload is None or result.payload.value is None
            else _descriptor_out(result.payload.value)
        )
        return _SlashLookupResponse(
            op=op,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post(
        "/ops/dynamic/classifications",
        response_model=_DynamicOpClassificationListResponse,
    )
    async def list_dynamic_op_classifications(
        request: Request,
    ) -> _DynamicOpClassificationListResponse:
        body = await read_json_body(request)
        req = _DescribeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.list_dynamic_op_classifications,
            meta=meta,
        )
        items = (
            []
            if result.payload is None
            else [_dynamic_op_classification_out(item) for item in result.payload.value]
        )
        return _DynamicOpClassificationListResponse(
            items=items,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post(
        "/ops/dynamic/classify",
        response_model=_DynamicOpClassificationListResponse,
    )
    async def classify_dynamic_op(
        request: Request,
    ) -> _DynamicOpClassificationListResponse:
        body = await read_json_body(request)
        req = _DynamicOpClassificationRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = await run_in_threadpool(
            service.classify_dynamic_op,
            meta=meta,
            op_id=req.op_id,
            effect=req.effect,
            approval=req.approval,
        )
        items = (
            []
            if result.payload is None
            else [_dynamic_op_classification_out(result.payload.value)]
        )
        return _DynamicOpClassificationListResponse(
            items=items,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/ops/invoke", response_model=_InvokeResponse)
    async def invoke_op(request: Request) -> _InvokeResponse:
        body = await read_json_body(request)
        req = _InvokeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        invocation = OpInvocationMetadata(
            actor=req.actor,
            source=req.source,
            channel=req.channel,
            invocation_id=req.invocation_id,
            parent_invocation_id=req.parent_invocation_id,
            confirmed=req.confirmed,
            approval_token=req.approval_token,
            reply_to_proposal_token=req.reply_to_proposal_token,
            reaction_to_proposal_token=req.reaction_to_proposal_token,
        )
        result = await run_in_threadpool(
            service.invoke_op,
            meta=meta,
            op_id=req.op_id,
            input_payload=req.input_payload,
            invocation=invocation,
        )
        payload = None if result.payload is None else result.payload.value
        return _InvokeResponse(
            output_json=_invoke_output_json(payload),
            policy=_policy_out(payload),
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


def _descriptor_out(d: OpDescriptor) -> _OpDescriptorOut:
    return _OpDescriptorOut(
        op_id=d.op_id,
        kind=d.kind,
        version=d.version,
        summary=d.summary,
        input_schema=d.input_schema,
        output_schema=d.output_schema,
        simple_output_path=d.simple_output_path,
        effect=d.effect,
        approval=d.approval,
        required_ops=d.required_ops,
        slash_command_name=d.slash_command_name,
        slash_command_aliases=d.slash_command_aliases,
        slash_command_description=d.slash_command_description,
    )


def _search_hit_out(value: OpSearchHit) -> _OpSearchHitOut:
    return _OpSearchHitOut(
        op_id=value.op_id,
        required_params=list(value.required_params),
        summary=value.summary,
    )


def _tool_system_hint_out(value: ToolSystemHint) -> _ToolSystemHintOut:
    return _ToolSystemHintOut(
        system_id=value.system_id,
        label=value.label,
        summary=value.summary,
        kind=value.kind,
        ready=value.ready,
        tool_count=value.tool_count,
        pending_tool_count=value.pending_tool_count,
    )


def _dynamic_op_classification_out(
    value: DynamicOpClassificationRow,
) -> _DynamicOpClassificationOut:
    """Project one dynamic op classification row into the API DTO."""
    return _DynamicOpClassificationOut(
        op_id=value.op_id,
        source_kind=value.source_kind,
        source_ref=value.source_ref,
        definition_digest=value.definition_digest,
        summary=value.summary,
        input_schema=value.input_schema,
        output_schema=value.output_schema,
        effect=value.effect,
        approval=value.approval,
    )


def _invoke_output_json(payload: OpInvokeResult | None) -> str:
    if payload is None or payload.output is None:
        return ""
    return json.dumps(payload.output)


def _policy_out(payload: OpInvokeResult | None) -> _PolicyDecision:
    if payload is None:
        return _PolicyDecision(
            decision_id="",
            allowed=False,
            reason_codes=[],
            obligations=[],
            proposal_id="",
        )
    return _PolicyDecision(
        decision_id=payload.policy_decision_id,
        allowed=payload.policy_allowed,
        reason_codes=list(payload.policy_reason_codes),
        obligations=list(payload.policy_obligations),
        proposal_id=payload.proposal_token,
    )


def _error_out(error: ErrorDetail) -> _ErrorOut:
    return _ErrorOut(
        code=error.code,
        message=error.message,
        category=error.category.value,
        retryable=error.retryable,
        metadata=dict(error.metadata) if error.metadata else {},
    )
