"""gRPC adapter entrypoints for Attention Router Service."""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import grpc
from brain.action.v1 import attention_router_pb2, attention_router_pb2_grpc
from brain.shared.v1 import envelope_pb2
from packages.brain_shared.envelope import Envelope, EnvelopeKind, EnvelopeMeta
from packages.brain_shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    validation_error,
)
from services.action.attention_router.domain import HealthStatus
from services.action.attention_router.implementation import map_policy_approval_payload
from services.action.attention_router.service import AttentionRouterService


class GrpcAttentionRouterService(
    attention_router_pb2_grpc.AttentionRouterServiceServicer
):
    """gRPC servicer mapping transport requests into native AR API calls."""

    def __init__(self, service: AttentionRouterService) -> None:
        self._service = service

    def RouteNotification(
        self,
        request: attention_router_pb2.RouteNotificationRequest,
        context: grpc.ServicerContext,
    ) -> attention_router_pb2.RouteNotificationResponse:
        result = self._service.route_notification(
            meta=_meta_from_proto(request.metadata),
            actor=request.payload.actor,
            channel=request.payload.channel,
            title=request.payload.title,
            message=request.payload.message,
            recipient_e164=request.payload.recipient_e164,
            sender_e164=request.payload.sender_e164,
            dedupe_key=request.payload.dedupe_key,
            batch_key=request.payload.batch_key,
            force=request.payload.force,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = result.payload.value if result.payload is not None else None
        return attention_router_pb2.RouteNotificationResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_route_result_to_proto(payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def RouteApprovalNotification(
        self,
        request: attention_router_pb2.RouteApprovalNotificationRequest,
        context: grpc.ServicerContext,
    ) -> attention_router_pb2.RouteNotificationResponse:
        payload = request.payload
        try:
            expires_at = _parse_utc_datetime(payload.expires_at)
        except ValueError:
            meta = _meta_from_proto(request.metadata)
            return attention_router_pb2.RouteNotificationResponse(
                metadata=_meta_to_proto(meta),
                payload=attention_router_pb2.RouteNotificationResult(),
                errors=[
                    _error_to_proto(
                        validation_error(
                            "expires_at must be a valid ISO-8601 timestamp",
                            code=codes.INVALID_ARGUMENT,
                        )
                    )
                ],
            )
        approval = map_policy_approval_payload(
            proposal_token=payload.proposal_token,
            capability_id=payload.capability_id,
            capability_version=payload.capability_version,
            summary=payload.summary,
            actor=payload.actor,
            channel=payload.channel,
            trace_id=payload.trace_id,
            invocation_id=payload.invocation_id,
            expires_at=expires_at,
        )
        result = self._service.route_approval_notification(
            meta=_meta_from_proto(request.metadata),
            approval=approval,
        )
        _abort_for_transport_errors(context=context, result=result)
        route_payload = result.payload.value if result.payload is not None else None
        return attention_router_pb2.RouteNotificationResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_route_result_to_proto(route_payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def FlushBatch(
        self,
        request: attention_router_pb2.FlushBatchRequest,
        context: grpc.ServicerContext,
    ) -> attention_router_pb2.RouteNotificationResponse:
        result = self._service.flush_batch(
            meta=_meta_from_proto(request.metadata),
            batch_key=request.payload.batch_key,
            actor=request.payload.actor,
            channel=request.payload.channel,
            recipient_e164=request.payload.recipient_e164,
            sender_e164=request.payload.sender_e164,
            title=request.payload.title,
        )
        _abort_for_transport_errors(context=context, result=result)
        payload = result.payload.value if result.payload is not None else None
        return attention_router_pb2.RouteNotificationResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_route_result_to_proto(payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def CorrelateApprovalResponse(
        self,
        request: attention_router_pb2.CorrelateApprovalResponseRequest,
        context: grpc.ServicerContext,
    ) -> attention_router_pb2.CorrelateApprovalResponseResponse:
        payload = request.payload
        result = self._service.correlate_approval_response(
            meta=_meta_from_proto(request.metadata),
            actor=payload.actor,
            channel=payload.channel,
            message_text=payload.message_text,
            approval_token=payload.approval_token,
            reply_to_proposal_token=payload.reply_to_proposal_token,
            reaction_to_proposal_token=payload.reaction_to_proposal_token,
        )
        _abort_for_transport_errors(context=context, result=result)
        normalized = result.payload.value if result.payload is not None else None
        return attention_router_pb2.CorrelateApprovalResponseResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_approval_correlation_to_proto(normalized),
            errors=[_error_to_proto(item) for item in result.errors],
        )

    def Health(
        self,
        request: attention_router_pb2.AttentionRouterHealthRequest,
        context: grpc.ServicerContext,
    ) -> attention_router_pb2.AttentionRouterHealthResponse:
        result = self._service.health(meta=_meta_from_proto(request.metadata))
        _abort_for_transport_errors(context=context, result=result)
        payload = result.payload.value if result.payload is not None else None
        return attention_router_pb2.AttentionRouterHealthResponse(
            metadata=_meta_to_proto(result.metadata),
            payload=_health_to_proto(payload),
            errors=[_error_to_proto(item) for item in result.errors],
        )


def register_grpc(*, server: grpc.Server, service: AttentionRouterService) -> None:
    """Register Attention Router gRPC service implementation on one server."""
    attention_router_pb2_grpc.add_AttentionRouterServiceServicer_to_server(
        GrpcAttentionRouterService(service=service),
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


def _route_result_to_proto(
    payload: object,
) -> attention_router_pb2.RouteNotificationResult:
    """Convert route result domain payload into protobuf shape."""
    if payload is None:
        return attention_router_pb2.RouteNotificationResult()
    assert hasattr(payload, "decision")
    notification = getattr(payload, "notification", None)
    proto_notification = attention_router_pb2.RoutedNotification()
    if notification is not None:
        proto_notification = attention_router_pb2.RoutedNotification(
            actor=notification.actor,
            channel=notification.channel,
            recipient=notification.recipient,
            sender=notification.sender,
            message=notification.message,
            title=notification.title,
            dedupe_key=notification.dedupe_key,
            batch_key=notification.batch_key,
        )
    return attention_router_pb2.RouteNotificationResult(
        decision=payload.decision,
        delivered=payload.delivered,
        detail=payload.detail,
        suppressed_reason=payload.suppressed_reason,
        batched_count=payload.batched_count,
        notification=proto_notification,
    )


def _health_to_proto(
    payload: HealthStatus | None,
) -> attention_router_pb2.AttentionRouterHealthStatus:
    """Convert health domain payload into protobuf shape."""
    if payload is None:
        return attention_router_pb2.AttentionRouterHealthStatus()
    return attention_router_pb2.AttentionRouterHealthStatus(
        service_ready=payload.service_ready,
        adapter_ready=payload.adapter_ready,
        detail=payload.detail,
    )


def _approval_correlation_to_proto(
    payload: object,
) -> attention_router_pb2.ApprovalCorrelationPayload:
    """Convert approval-correlation domain payload into protobuf shape."""
    if payload is None:
        return attention_router_pb2.ApprovalCorrelationPayload()
    assert hasattr(payload, "actor")
    return attention_router_pb2.ApprovalCorrelationPayload(
        actor=payload.actor,
        channel=payload.channel,
        message_text=payload.message_text,
        approval_token=payload.approval_token,
        reply_to_proposal_token=payload.reply_to_proposal_token,
        reaction_to_proposal_token=payload.reaction_to_proposal_token,
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


def _parse_utc_datetime(raw: str) -> datetime:
    """Parse RFC3339-like datetime string and normalize to UTC."""
    text = raw.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
