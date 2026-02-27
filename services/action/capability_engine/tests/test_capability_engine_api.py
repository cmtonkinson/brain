"""Adapter tests for Capability Engine gRPC transport/domain mapping."""
# ruff: noqa: E402

from __future__ import annotations

import sys
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
from services.action.capability_engine.api import (  # noqa: E402
    GrpcCapabilityEngineService,
    _abort_for_transport_errors,
    _meta_to_proto,
)
from services.action.capability_engine.domain import (  # noqa: E402
    CapabilityDescriptor,
)
from brain.action.v1 import capability_engine_pb2  # noqa: E402


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


class _FakeCesService:
    """CES fake with programmable envelopes for gRPC adapter testing."""

    def __init__(self) -> None:
        self.describe_result: Envelope[tuple[CapabilityDescriptor, ...]] = success(
            meta=_meta(), payload=()
        )

    def describe_capabilities(self, *, meta: EnvelopeMeta):
        del meta
        return self.describe_result

    def invoke_capability(self, **_kwargs):  # type: ignore[override]
        raise NotImplementedError("not used in these tests")

    def health(self, *, meta: EnvelopeMeta):  # type: ignore[override]
        raise NotImplementedError("not used in these tests")


def _meta() -> EnvelopeMeta:
    """Build valid envelope metadata for transport tests."""
    return new_meta(kind=EnvelopeKind.COMMAND, source="grpc-test", principal="operator")


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


def test_abort_maps_internal_errors_to_internal() -> None:
    """Internal-category errors must map to gRPC INTERNAL transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.INTERNAL)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.INTERNAL


def test_describe_capabilities_returns_all_descriptors() -> None:
    """DescribeCapabilities response includes one proto message per descriptor."""
    service = _FakeCesService()
    service.describe_result = success(
        meta=_meta(),
        payload=(
            CapabilityDescriptor(
                capability_id="demo-op",
                kind="op",
                version="1.0.0",
                summary="An op",
                input_types=("str",),
                output_types=("str",),
                autonomy=0,
                requires_approval=False,
                side_effects=(),
                required_capabilities=(),
            ),
            CapabilityDescriptor(
                capability_id="demo-skill",
                kind="skill",
                version="2.0.0",
                summary="A skill",
                input_types=("dict[str, object]",),
                output_types=("dict[str, object]",),
                autonomy=1,
                requires_approval=True,
                side_effects=("writes_db",),
                required_capabilities=("demo-op",),
            ),
        ),
    )
    grpc_service = GrpcCapabilityEngineService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.DescribeCapabilities(
        capability_engine_pb2.DescribeCapabilitiesRequest(
            metadata=_meta_to_proto(_meta())
        ),
        context,
    )

    assert len(response.errors) == 0
    assert len(response.capabilities) == 2

    by_id = {c.capability_id: c for c in response.capabilities}

    op = by_id["demo-op"]
    assert op.kind == "op"
    assert op.version == "1.0.0"
    assert op.summary == "An op"
    assert list(op.input_types) == ["str"]
    assert list(op.output_types) == ["str"]
    assert op.autonomy == 0
    assert op.requires_approval is False
    assert list(op.side_effects) == []
    assert list(op.required_capabilities) == []

    skill = by_id["demo-skill"]
    assert skill.kind == "skill"
    assert skill.version == "2.0.0"
    assert skill.autonomy == 1
    assert skill.requires_approval is True
    assert list(skill.side_effects) == ["writes_db"]
    assert list(skill.required_capabilities) == ["demo-op"]


def test_describe_capabilities_returns_empty_list_when_none_registered() -> None:
    """DescribeCapabilities with no registered capabilities returns empty list."""
    service = _FakeCesService()
    grpc_service = GrpcCapabilityEngineService(service=service)
    context = _FakeServicerContext()

    response = grpc_service.DescribeCapabilities(
        capability_engine_pb2.DescribeCapabilitiesRequest(
            metadata=_meta_to_proto(_meta())
        ),
        context,
    )

    assert len(response.errors) == 0
    assert list(response.capabilities) == []


def test_describe_capabilities_aborts_on_internal_error() -> None:
    """DescribeCapabilities should abort with INTERNAL on internal-category failures."""
    service = _FakeCesService()
    service.describe_result = _envelope_with_error(category=ErrorCategory.INTERNAL)
    grpc_service = GrpcCapabilityEngineService(service=service)
    context = _FakeServicerContext()

    with pytest.raises(_AbortCalled):
        grpc_service.DescribeCapabilities(
            capability_engine_pb2.DescribeCapabilitiesRequest(
                metadata=_meta_to_proto(_meta())
            ),
            context,
        )

    assert context.code == grpc.StatusCode.INTERNAL
