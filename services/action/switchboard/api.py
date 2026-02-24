"""gRPC adapter entrypoints for Switchboard Service."""

from __future__ import annotations

from datetime import datetime, timezone

import grpc
from brain.action.v1 import switchboard_pb2, switchboard_pb2_grpc
from brain.shared.v1 import envelope_pb2
from google.protobuf import wrappers_pb2
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import ErrorCategory, ErrorDetail
from services.action.switchboard.domain import (
    HealthStatus,
    IngestResult,
    NormalizedSignalMessage,
    RegisterSignalWebhookResult,
)
from services.action.switchboard.service import SwitchboardService


class GrpcSwitchboardService(switchboard_pb2_grpc.SwitchboardServiceServicer):
    """gRPC servicer mapping transport requests into native Switchboard API calls."""

    def __init__(self, service: SwitchboardService) -> None:
        self._service = service

    def IngestSignalWebhook(
        self,
        request: switchboard_pb2.IngestSignalWebhookRequest,
        context: grpc.ServicerContext,
    ) -> switchboard_pb2.IngestSignalWebhookResponse:
        result = self._service.ingest_signal_webhook(
            meta=_meta_from_proto(request.metadata),
            raw_body_json=request.payload.raw_body_json,
            header_timestamp=request.payload.header_timestamp,
            header_signature=request.payload.header_signature,
        )
        _abort_for_transport_errors(context=context, result=result)
        return switchboard_pb2.IngestSignalWebhookResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_ingest_result_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def RegisterSignalWebhook(
        self,
        request: switchboard_pb2.RegisterSignalWebhookRequest,
        context: grpc.ServicerContext,
    ) -> switchboard_pb2.RegisterSignalWebhookResponse:
        result = self._service.register_signal_webhook(
            meta=_meta_from_proto(request.metadata),
            callback_url=request.payload.callback_url,
            shared_secret_ref=request.payload.shared_secret_ref,
        )
        _abort_for_transport_errors(context=context, result=result)
        return switchboard_pb2.RegisterSignalWebhookResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_register_result_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def Health(
        self,
        request: switchboard_pb2.SwitchboardHealthRequest,
        context: grpc.ServicerContext,
    ) -> switchboard_pb2.SwitchboardHealthResponse:
        result = self._service.health(meta=_meta_from_proto(request.metadata))
        _abort_for_transport_errors(context=context, result=result)
        return switchboard_pb2.SwitchboardHealthResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_health_to_proto(
                None if result.payload is None else result.payload.value
            ),
            errors=[_error_to_proto(item) for item in result.errors],
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


def _ingest_result_to_proto(
    payload: IngestResult | None,
) -> switchboard_pb2.IngestResult:
    """Convert ingest domain payload into protobuf shape."""
    if payload is None:
        return switchboard_pb2.IngestResult()

    message = _normalized_message_to_proto(payload.message)
    return switchboard_pb2.IngestResult(
        accepted=payload.accepted,
        queued=payload.queued,
        queue_name=payload.queue_name,
        reason=payload.reason,
        message=message,
    )


def _register_result_to_proto(
    payload: RegisterSignalWebhookResult | None,
) -> switchboard_pb2.RegisterSignalWebhookResult:
    """Convert registration domain payload into protobuf shape."""
    if payload is None:
        return switchboard_pb2.RegisterSignalWebhookResult()
    return switchboard_pb2.RegisterSignalWebhookResult(
        registered=payload.registered,
        callback_url=payload.callback_url,
        shared_secret_ref=payload.shared_secret_ref,
        detail=payload.detail,
    )


def _health_to_proto(
    payload: HealthStatus | None,
) -> switchboard_pb2.SwitchboardHealthStatus:
    """Convert health domain payload into protobuf shape."""
    if payload is None:
        return switchboard_pb2.SwitchboardHealthStatus()
    return switchboard_pb2.SwitchboardHealthStatus(
        service_ready=payload.service_ready,
        adapter_ready=payload.adapter_ready,
        cas_ready=payload.cas_ready,
        detail=payload.detail,
    )


def _normalized_message_to_proto(
    payload: NormalizedSignalMessage | None,
) -> switchboard_pb2.NormalizedSignalMessage:
    """Convert normalized message payload into protobuf shape."""
    if payload is None:
        return switchboard_pb2.NormalizedSignalMessage()

    result = switchboard_pb2.NormalizedSignalMessage(
        sender_e164=payload.sender_e164,
        message_text=payload.message_text,
        timestamp_ms=payload.timestamp_ms,
        source_device=payload.source_device,
        source=payload.source,
    )
    if payload.group_id is not None:
        result.group_id.CopyFrom(wrappers_pb2.StringValue(value=payload.group_id))
    if payload.quote_target_timestamp_ms is not None:
        result.quote_target_timestamp_ms.CopyFrom(
            wrappers_pb2.Int64Value(value=payload.quote_target_timestamp_ms)
        )
    if payload.reaction_target_timestamp_ms is not None:
        result.reaction_target_timestamp_ms.CopyFrom(
            wrappers_pb2.Int64Value(value=payload.reaction_target_timestamp_ms)
        )
    return result


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
