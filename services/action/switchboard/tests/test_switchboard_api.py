"""Adapter tests for Switchboard gRPC transport/domain error mapping semantics."""
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
from services.action.switchboard.api import (  # noqa: E402
    GrpcSwitchboardService,
    _abort_for_transport_errors,
    _meta_to_proto,
)
from services.action.switchboard.domain import (  # noqa: E402
    HealthStatus,
    IngestResult,
    NormalizedSignalMessage,
    RegisterSignalWebhookResult,
)
from brain.action.v1 import switchboard_pb2  # noqa: E402


@dataclass(frozen=True)
class _Call:
    """One fake Switchboard call captured by method name."""

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


class _FakeSwitchboardService:
    """Service fake with programmable envelopes for gRPC adapter testing."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.ingest_result = success(
            meta=_meta(),
            payload=IngestResult(
                accepted=True,
                queued=True,
                queue_name="signal_inbound",
                reason="accepted",
                message=NormalizedSignalMessage(
                    sender_e164="+12025550100",
                    message_text="hello",
                    timestamp_ms=123,
                    source_device="1",
                    source="signal",
                    group_id="group-1",
                    quote_target_timestamp_ms=100,
                    reaction_target_timestamp_ms=101,
                ),
            ),
        )
        self.register_result = success(
            meta=_meta(),
            payload=RegisterSignalWebhookResult(
                registered=True,
                callback_url="https://example.com",
                detail="registered",
            ),
        )
        self.health_result = success(
            meta=_meta(),
            payload=HealthStatus(
                service_ready=True,
                adapter_ready=True,
                cas_ready=True,
                detail="ok",
            ),
        )

    def ingest_signal_webhook(
        self, *, meta, raw_body_json, header_timestamp, header_signature
    ):
        del meta, raw_body_json, header_timestamp, header_signature
        self.calls.append(_Call(method="ingest_signal_webhook"))
        return self.ingest_result

    def register_signal_webhook(self, *, meta, callback_url):
        del meta, callback_url
        self.calls.append(_Call(method="register_signal_webhook"))
        return self.register_result

    def health(self, *, meta):
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


def test_ingest_routes_to_service_and_maps_wrapper_fields() -> None:
    """Ingest should route to service and map wrapper payload fields to proto."""
    service = _FakeSwitchboardService()
    grpc_service = GrpcSwitchboardService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.IngestSignalWebhook(
        switchboard_pb2.IngestSignalWebhookRequest(
            metadata=_meta_to_proto(_meta()),
            payload=switchboard_pb2.IngestSignalWebhookPayload(
                raw_body_json="{}",
                header_timestamp="1",
                header_signature="sig",
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(method="ingest_signal_webhook")
    assert response.payload.accepted is True
    assert response.payload.message.sender_e164 == "+12025550100"
    assert response.payload.message.group_id.value == "group-1"
    assert response.payload.message.quote_target_timestamp_ms.value == 100
    assert response.payload.message.reaction_target_timestamp_ms.value == 101


def test_register_routes_to_service_and_maps_payload() -> None:
    """Registration should route to service and return mapped payload fields."""
    service = _FakeSwitchboardService()
    grpc_service = GrpcSwitchboardService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.RegisterSignalWebhook(
        switchboard_pb2.RegisterSignalWebhookRequest(
            metadata=_meta_to_proto(_meta()),
            payload=switchboard_pb2.RegisterSignalWebhookPayload(
                callback_url="https://example.com/switchboard/signal",
            ),
        ),
        context,
    )

    assert service.calls[-1] == _Call(method="register_signal_webhook")
    assert response.payload.registered is True
    assert response.payload.callback_url == "https://example.com"


def test_health_aborts_transport_on_internal_error() -> None:
    """Health should abort with INTERNAL on internal-category failures."""
    service = _FakeSwitchboardService()
    service.health_result = _envelope_with_error(category=ErrorCategory.INTERNAL)
    grpc_service = GrpcSwitchboardService(service=service)
    context = _FakeServicerContext()

    with pytest.raises(_AbortCalled):
        grpc_service.Health(
            switchboard_pb2.SwitchboardHealthRequest(metadata=_meta_to_proto(_meta())),
            context,
        )

    assert context.code == grpc.StatusCode.INTERNAL
