"""FastAPI route adapters for Capability Engine Service."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, new_meta
from packages.brain_shared.errors import ErrorCategory
from packages.brain_shared.http.server import read_json_body
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
)
from services.action.capability_engine.service import CapabilityEngineService


class _DescribeRequest(BaseModel):
    source: str = "unknown"
    principal: str = "unknown"
    trace_id: str | None = None
    envelope_id: str | None = None
    parent_id: str = ""


class _CapabilityDescriptorOut(BaseModel):
    capability_id: str
    kind: str
    version: str
    summary: str
    input_types: tuple[str, ...]
    output_types: tuple[str, ...]
    autonomy: int
    requires_approval: bool
    side_effects: tuple[str, ...]
    required_capabilities: tuple[str, ...]


class _ErrorOut(BaseModel):
    code: str
    message: str
    category: str
    retryable: bool
    metadata: dict[str, str]


class _DescribeResponse(BaseModel):
    capabilities: list[_CapabilityDescriptorOut]
    errors: list[_ErrorOut]


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
    capability_id: str
    input_payload: dict[str, Any] = {}
    actor: str = ""
    channel: str = ""
    invocation_id: str = ""
    parent_invocation_id: str = ""
    confirmed: bool = False
    approval_token: str = ""


class _InvokeResponse(BaseModel):
    output_json: str
    policy: _PolicyDecision
    errors: list[_ErrorOut]


def register_routes(*, router: APIRouter, service: CapabilityEngineService) -> None:
    """Register Capability Engine routes on one router."""

    @router.post("/capabilities/describe", response_model=_DescribeResponse)
    async def describe_capabilities(request: Request) -> _DescribeResponse:
        body = await read_json_body(request)
        req = _DescribeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        result = service.describe_capabilities(meta=meta)
        capabilities = (
            []
            if result.payload is None
            else [_descriptor_out(item) for item in result.payload.value]
        )
        return _DescribeResponse(
            capabilities=capabilities,
            errors=[_error_out(e) for e in result.errors],
        )

    @router.post("/capabilities/invoke", response_model=_InvokeResponse)
    async def invoke_capability(request: Request) -> _InvokeResponse:
        body = await read_json_body(request)
        req = _InvokeRequest.model_validate(body)
        meta = _meta_from_request(
            req.source, req.principal, req.trace_id, req.parent_id, req.envelope_id
        )
        invocation = CapabilityInvocationMetadata(
            actor=req.actor,
            source=req.source,
            channel=req.channel,
            invocation_id=req.invocation_id,
            parent_invocation_id=req.parent_invocation_id,
            confirmed=req.confirmed,
            approval_token=req.approval_token,
        )
        result = service.invoke_capability(
            meta=meta,
            capability_id=req.capability_id,
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


def _descriptor_out(d: CapabilityDescriptor) -> _CapabilityDescriptorOut:
    return _CapabilityDescriptorOut(
        capability_id=d.capability_id,
        kind=d.kind,
        version=d.version,
        summary=d.summary,
        input_types=d.input_types,
        output_types=d.output_types,
        autonomy=d.autonomy,
        requires_approval=d.requires_approval,
        side_effects=d.side_effects,
        required_capabilities=d.required_capabilities,
    )


def _invoke_output_json(payload: CapabilityInvokeResult | None) -> str:
    if payload is None or payload.output is None:
        return ""
    return json.dumps(payload.output)


def _policy_out(payload: CapabilityInvokeResult | None) -> _PolicyDecision:
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
