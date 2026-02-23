"""Adapter tests for EAS gRPC transport/domain error mapping semantics."""
# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

import grpc
import pytest


def _repo_root() -> Path:
    """Resolve repository root by walking up to the directory containing Makefile."""
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

from packages.brain_shared.envelope import EnvelopeKind, new_meta  # noqa: E402
from packages.brain_shared.envelope.envelope import Envelope  # noqa: E402
from packages.brain_shared.errors import (
    ErrorCategory,
    codes,
    dependency_error,
    internal_error,
    validation_error,
)  # noqa: E402
from services.state.embedding_authority.api import _abort_for_transport_errors  # noqa: E402


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


def _envelope_with_error(*, category: ErrorCategory) -> Envelope[object]:
    """Construct one failed envelope with selected error category."""
    meta = new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")
    if category == ErrorCategory.DEPENDENCY:
        error = dependency_error(
            "dependency unavailable", code=codes.DEPENDENCY_UNAVAILABLE
        )
    elif category == ErrorCategory.INTERNAL:
        error = internal_error("internal failure", code=codes.INTERNAL_ERROR)
    else:
        error = validation_error("invalid", code=codes.INVALID_ARGUMENT)
    return Envelope(metadata=meta, payload=None, errors=[error])


def test_abort_maps_dependency_errors_to_unavailable() -> None:
    """Dependency-category errors must map to gRPC UNAVAILABLE transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.DEPENDENCY)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.UNAVAILABLE
    assert context.details is not None
    assert "dependency unavailable" in context.details


def test_abort_maps_internal_errors_to_internal() -> None:
    """Internal-category errors must map to gRPC INTERNAL transport failures."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.INTERNAL)

    with pytest.raises(_AbortCalled):
        _abort_for_transport_errors(context=context, result=envelope)

    assert context.code == grpc.StatusCode.INTERNAL
    assert context.details is not None
    assert "internal failure" in context.details


def test_abort_ignores_domain_errors() -> None:
    """Domain errors should stay in envelope errors and not abort transport."""
    context = _FakeServicerContext()
    envelope = _envelope_with_error(category=ErrorCategory.VALIDATION)

    _abort_for_transport_errors(context=context, result=envelope)

    assert context.code is None
    assert context.details is None
