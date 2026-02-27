"""gRPC adapter entrypoints for Capability Engine Service."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.action.v1 import capability_engine_pb2, capability_engine_pb2_grpc
from brain.shared.v1 import envelope_pb2
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.capability_engine.domain import (
    CapabilityDescriptor,
    CapabilityInvocationMetadata,
    CapabilityInvokeResult,
)
from services.action.capability_engine.service import CapabilityEngineService


class GrpcCapabilityEngineService(
    capability_engine_pb2_grpc.CapabilityEngineServiceServicer
):
    """gRPC servicer mapping transport requests into native CES API calls."""

    def __init__(self, service: CapabilityEngineService) -> None:
        self._service = service

    def DescribeCapabilities(
        self,
        request: capability_engine_pb2.DescribeCapabilitiesRequest,
        context: grpc.ServicerContext,
    ) -> capability_engine_pb2.DescribeCapabilitiesResponse:
        result = self._service.describe_capabilities(
            meta=_meta_from_proto(request.metadata)
        )
        _abort_for_transport_errors(context=context, result=result)
        capabilities = (
            []
            if result.payload is None
            else [_descriptor_to_proto(item) for item in result.payload.value]
        )
        return capability_engine_pb2.DescribeCapabilitiesResponse(
            metadata=_meta_to_proto(result.metadata),
            capabilities=capabilities,
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def InvokeCapability(
        self,
        request: capability_engine_pb2.InvokeCapabilityRequest,
        context: grpc.ServicerContext,
    ) -> capability_engine_pb2.InvokeCapabilityResponse:
        import json

        try:
            input_payload: dict[str, object] = json.loads(request.input_json or "{}")
        except json.JSONDecodeError:
            input_payload = {}

        invocation = CapabilityInvocationMetadata(
            actor=request.policy_context.actor,
            source=request.metadata.source,
            channel=request.policy_context.channel,
            invocation_id=request.policy_context.invocation_id,
            parent_invocation_id=request.policy_context.parent_invocation_id,
            confirmed=request.policy_context.confirmed,
            approval_token=request.policy_context.approval_token,
        )
        result = self._service.invoke_capability(
            meta=_meta_from_proto(request.metadata),
            capability_id=request.capability.name,
            input_payload=input_payload,
            invocation=invocation,
        )
        _abort_for_transport_errors(context=context, result=result)
        return capability_engine_pb2.InvokeCapabilityResponse(
            metadata=_meta_to_proto(result.metadata),
            output_json=_invoke_output_json(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
            policy=_policy_to_proto(
                None if result.payload is None else result.payload.value
            ),
        )


def register_grpc(*, server: grpc.Server, service: CapabilityEngineService) -> None:
    """Register Capability Engine gRPC service implementation on one server."""
    capability_engine_pb2_grpc.add_CapabilityEngineServiceServicer_to_server(
        GrpcCapabilityEngineService(service=service),
        server,
    )


def _abort_for_transport_errors(
    *,
    context: grpc.ServicerContext,
    result: Envelope[object],
) -> None:
    """Abort gRPC transport for dependency/internal category failures."""
    dependency_messages = [
        error.message
        for error in result.errors
        if error.category == ErrorCategory.DEPENDENCY
    ]
    if len(dependency_messages) > 0:
        context.abort(grpc.StatusCode.UNAVAILABLE, "; ".join(dependency_messages))

    internal_messages = [
        error.message
        for error in result.errors
        if error.category == ErrorCategory.INTERNAL
    ]
    if len(internal_messages) > 0:
        context.abort(grpc.StatusCode.INTERNAL, "; ".join(internal_messages))


def _meta_from_proto(meta: envelope_pb2.EnvelopeMeta) -> EnvelopeMeta:
    """Convert protobuf metadata into canonical envelope metadata."""
    if meta.timestamp.seconds == 0 and meta.timestamp.nanos == 0:
        timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.fromtimestamp(
            meta.timestamp.seconds + (meta.timestamp.nanos / 1_000_000_000),
            tz=timezone.utc,
        )
    return EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        timestamp=timestamp,
        kind=_kind_from_proto(meta.kind),
        source=meta.source,
        principal=meta.principal,
    )


def _meta_to_proto(meta: EnvelopeMeta) -> envelope_pb2.EnvelopeMeta:
    """Convert canonical metadata into protobuf shape."""
    seconds = int(meta.timestamp.timestamp())
    nanos = int((meta.timestamp.timestamp() - seconds) * 1_000_000_000)
    return envelope_pb2.EnvelopeMeta(
        envelope_id=meta.envelope_id,
        trace_id=meta.trace_id,
        parent_id=meta.parent_id,
        kind=_kind_to_proto(meta.kind),
        timestamp={"seconds": seconds, "nanos": nanos},
        source=meta.source,
        principal=meta.principal,
    )


def _kind_from_proto(kind: int) -> EnvelopeKind:
    """Map protobuf envelope kind enum to canonical kind."""
    if kind == envelope_pb2.ENVELOPE_KIND_COMMAND:
        return EnvelopeKind.COMMAND
    if kind == envelope_pb2.ENVELOPE_KIND_EVENT:
        return EnvelopeKind.EVENT
    if kind == envelope_pb2.ENVELOPE_KIND_RESULT:
        return EnvelopeKind.RESULT
    if kind == envelope_pb2.ENVELOPE_KIND_STREAM:
        return EnvelopeKind.STREAM
    return EnvelopeKind.UNSPECIFIED


def _kind_to_proto(kind: EnvelopeKind) -> int:
    """Map canonical envelope kind to protobuf enum value."""
    if kind == EnvelopeKind.COMMAND:
        return envelope_pb2.ENVELOPE_KIND_COMMAND
    if kind == EnvelopeKind.EVENT:
        return envelope_pb2.ENVELOPE_KIND_EVENT
    if kind == EnvelopeKind.RESULT:
        return envelope_pb2.ENVELOPE_KIND_RESULT
    if kind == EnvelopeKind.STREAM:
        return envelope_pb2.ENVELOPE_KIND_STREAM
    return envelope_pb2.ENVELOPE_KIND_UNSPECIFIED


def _descriptor_to_proto(
    descriptor: CapabilityDescriptor,
) -> capability_engine_pb2.CapabilityDescriptor:
    """Convert one domain capability descriptor into its protobuf shape."""
    return capability_engine_pb2.CapabilityDescriptor(
        capability_id=descriptor.capability_id,
        kind=descriptor.kind,
        version=descriptor.version,
        summary=descriptor.summary,
        input_types=list(descriptor.input_types),
        output_types=list(descriptor.output_types),
        autonomy=descriptor.autonomy,
        requires_approval=descriptor.requires_approval,
        side_effects=list(descriptor.side_effects),
        required_capabilities=list(descriptor.required_capabilities),
    )


def _invoke_output_json(payload: CapabilityInvokeResult | None) -> str:
    """Serialize invoke output dict to JSON string, empty string on no output."""
    import json

    if payload is None or payload.output is None:
        return ""
    return json.dumps(payload.output)


def _policy_to_proto(
    payload: CapabilityInvokeResult | None,
) -> capability_engine_pb2.PolicyDecisionSummary:
    """Convert policy fields from invoke result into protobuf shape."""
    if payload is None:
        return capability_engine_pb2.PolicyDecisionSummary()
    return capability_engine_pb2.PolicyDecisionSummary(
        decision_id=payload.policy_decision_id,
        allowed=payload.policy_allowed,
        reason_codes=list(payload.policy_reason_codes),
        obligations=list(payload.policy_obligations),
        proposal_id=payload.proposal_token,
    )


def _error_to_proto(error: ErrorDetail) -> envelope_pb2.ErrorDetail:
    """Convert one canonical shared error detail into protobuf shape."""
    return envelope_pb2.ErrorDetail(
        code=error.code,
        message=error.message,
        category=_category_to_proto(error.category),
        retryable=error.retryable,
        metadata=dict(error.metadata),
    )


def _category_to_proto(category: ErrorCategory) -> int:
    """Map shared error category enum into protobuf enum value."""
    if category == ErrorCategory.VALIDATION:
        return envelope_pb2.ERROR_CATEGORY_VALIDATION
    if category == ErrorCategory.CONFLICT:
        return envelope_pb2.ERROR_CATEGORY_CONFLICT
    if category == ErrorCategory.NOT_FOUND:
        return envelope_pb2.ERROR_CATEGORY_NOT_FOUND
    if category == ErrorCategory.POLICY:
        return envelope_pb2.ERROR_CATEGORY_POLICY
    if category == ErrorCategory.DEPENDENCY:
        return envelope_pb2.ERROR_CATEGORY_DEPENDENCY
    if category == ErrorCategory.INTERNAL:
        return envelope_pb2.ERROR_CATEGORY_INTERNAL
    return envelope_pb2.ERROR_CATEGORY_UNSPECIFIED
