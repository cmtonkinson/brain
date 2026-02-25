"""Adapter tests for Attention Router gRPC transport/domain mapping semantics."""
# ruff: noqa: E402

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import grpc
import pytest


def _repo_root() -> Path:
    """Resolve repository root by walking up to directory containing Makefile."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "Makefile").exists():
            return candidate
    raise RuntimeError("repository root not found from test path")


repo_root = _repo_root()
generated_root = repo_root / "generated"
if not generated_root.exists():
    pytest.skip(
        "generated protobuf stubs not present; run `make build` before this test",
        allow_module_level=True,
    )
sys.path.insert(0, str(generated_root))

from packages.brain_shared.envelope import (  # noqa: E402
    EnvelopeKind,
    EnvelopeMeta,
    failure,
    new_meta,
    success,
)
from packages.brain_shared.envelope.envelope import Envelope  # noqa: E402
from packages.brain_shared.errors import (  # noqa: E402
    ErrorCategory,
    codes,
    dependency_error,
    internal_error,
)
from services.action.attention_router.api import (  # noqa: E402
    GrpcAttentionRouterService,
    _abort_for_transport_errors,
    _meta_to_proto,
)
from services.action.attention_router.domain import (  # noqa: E402
    ApprovalCorrelationPayload,
    ApprovalNotificationPayload,
    HealthStatus,
    RouteNotificationResult,
    RoutedNotification,
)
from brain.action.v1 import attention_router_pb2  # noqa: E402


@dataclass(frozen=True)
class _Call:
    """One fake Attention Router call captured by method name."""

    method: str


class _AbortCalled(RuntimeError):
    """Raised by fake gRPC context when abort() is invoked."""


class _FakeServicerContext:
    """Minimal gRPC context stub for testing transport abort mapping."""

    def __init__(self) -> None:
        self.code: grpc.StatusCode | None = None
        self.details: str | None = None

    def abort(self, code: grpc.StatusCode, details: str) -> None:
        self.code = code
        self.details = details
        raise _AbortCalled(details)


class _FakeAttentionRouterService:
    """Service fake with programmable envelopes for gRPC adapter testing."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.route_result = success(
            meta=_meta(),
            payload=RouteNotificationResult(
                decision="sent",
                delivered=True,
                detail="ok",
                notification=RoutedNotification(
                    actor="operator",
                    channel="signal",
                    recipient="+12025550100",
                    sender="+12025550101",
                    message="hello",
                    title="",
                ),
            ),
        )
        self.health_result = success(
            meta=_meta(),
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=True,
                detail="ok",
            ),
        )

    def route_notification(self, *, meta, **kwargs):
        del meta, kwargs
        self.calls.append(_Call(method="route_notification"))
        return self.route_result

    def route_approval_notification(
        self, *, meta, approval: ApprovalNotificationPayload
    ):
        del meta, approval
        self.calls.append(_Call(method="route_approval_notification"))
        return self.route_result

    def flush_batch(self, *, meta, **kwargs):
        del meta, kwargs
        self.calls.append(_Call(method="flush_batch"))
        return self.route_result

    def correlate_approval_response(self, *, meta, **kwargs):
        del meta
        payload = ApprovalCorrelationPayload(
            actor=kwargs.get("actor", "operator"),
            channel=kwargs.get("channel", "signal"),
            message_text=kwargs.get("message_text", ""),
            approval_token=kwargs.get("approval_token", ""),
            reply_to_proposal_token=kwargs.get("reply_to_proposal_token", ""),
            reaction_to_proposal_token=kwargs.get("reaction_to_proposal_token", ""),
        )
        self.calls.append(_Call(method="correlate_approval_response"))
        return success(meta=_meta(), payload=payload)

    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        del meta
        self.calls.append(_Call(method="health"))
        return self.health_result


def _meta() -> EnvelopeMeta:
    """Build valid envelope metadata for transport tests."""
    return new_meta(kind=EnvelopeKind.EVENT, source="grpc-test", principal="operator")


def _envelope_with_error(*, category: ErrorCategory) -> Envelope[object]:
    """Construct one failed envelope with selected error category."""
    if category == ErrorCategory.DEPENDENCY:
        error = dependency_error(
            "dependency unavailable", code=codes.DEPENDENCY_UNAVAILABLE
        )
    else:
        error = internal_error("internal failure", code=codes.INTERNAL_ERROR)
    return failure(meta=_meta(), errors=[error])


def test_abort_maps_dependency_errors_to_unavailable() -> None:
    """Dependency-category errors must map to gRPC UNAVAILABLE transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.DEPENDENCY)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.UNAVAILABLE


def test_route_notification_maps_payload_fields() -> None:
    """RouteNotification should map service payload into protobuf response fields."""
    service = _FakeAttentionRouterService()
    grpc_service = GrpcAttentionRouterService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.RouteNotification(
        attention_router_pb2.RouteNotificationRequest(
            metadata=_meta_to_proto(_meta()),
            payload=attention_router_pb2.RouteNotificationPayload(
                actor="operator",
                channel="signal",
                message="hello",
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(method="route_notification")
    assert response.payload.decision == "sent"
    assert response.payload.notification.channel == "signal"
    assert response.errors == []


def test_health_aborts_transport_on_internal_error() -> None:
    """Health should abort with INTERNAL on internal-category failures."""
    service = _FakeAttentionRouterService()
    service.health_result = _envelope_with_error(category=ErrorCategory.INTERNAL)
    grpc_service = GrpcAttentionRouterService(service=service)
    context = _FakeServicerContext()

    with pytest.raises(_AbortCalled):
        grpc_service.Health(
            attention_router_pb2.AttentionRouterHealthRequest(
                metadata=_meta_to_proto(_meta())
            ),
            context,
        )

    assert context.code == grpc.StatusCode.INTERNAL


def test_correlate_approval_response_maps_payload_fields() -> None:
    """CorrelateApprovalResponse should map normalized payload fields."""
    service = _FakeAttentionRouterService()
    grpc_service = GrpcAttentionRouterService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.CorrelateApprovalResponse(
        attention_router_pb2.CorrelateApprovalResponseRequest(
            metadata=_meta_to_proto(_meta()),
            payload=attention_router_pb2.ApprovalCorrelationPayload(
                actor="operator",
                channel="signal",
                message_text="approve",
                reply_to_proposal_token="tok-1",
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(method="correlate_approval_response")
    assert response.payload.actor == "operator"
    assert response.payload.channel == "signal"
    assert response.payload.reply_to_proposal_token == "tok-1"
    assert response.errors == []


def test_route_approval_notification_rejects_invalid_expires_at() -> None:
    """Invalid approval expires_at should return validation error in payload."""
    service = _FakeAttentionRouterService()
    grpc_service = GrpcAttentionRouterService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.RouteApprovalNotification(
        attention_router_pb2.RouteApprovalNotificationRequest(
            metadata=_meta_to_proto(_meta()),
            payload=attention_router_pb2.PolicyApprovalNotificationPayload(
                proposal_token="tok-1",
                capability_id="cap.demo",
                capability_version="1.0.0",
                summary="approve me",
                actor="operator",
                channel="signal",
                trace_id="trace-1",
                invocation_id="inv-1",
                expires_at="not-a-time",
            ),
        ),
        context,
    )

    assert len(response.errors) == 1
    assert response.errors[0].code == codes.INVALID_ARGUMENT
    assert service.calls == []
