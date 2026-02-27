"""Unit tests for Brain SDK transport/domain error mapping."""

from __future__ import annotations

import grpc
import pytest


class _FakeRpcError(grpc.RpcError):
    def __init__(self, *, status: grpc.StatusCode, details: str) -> None:
        self._status = status
        self._details = details

    def code(self) -> grpc.StatusCode:
        return self._status

    def details(self) -> str:
        return self._details


def test_map_transport_error_marks_retryable_statuses() -> None:
    """UNAVAILABLE transport failures should map to retryable transport errors."""
    from packages.brain_sdk.errors import BrainTransportError, map_transport_error

    error = map_transport_error(
        operation="vault.get",
        error=_FakeRpcError(status=grpc.StatusCode.UNAVAILABLE, details="down"),
    )

    assert isinstance(error, BrainTransportError)
    assert error.retryable is True
    assert error.status_code == grpc.StatusCode.UNAVAILABLE


def test_raise_for_domain_errors_raises_typed_category_error() -> None:
    """Validation response errors should map to ``BrainValidationError``."""
    from packages.brain_sdk._generated import envelope_pb2
    from packages.brain_sdk.errors import BrainValidationError, raise_for_domain_errors

    with pytest.raises(BrainValidationError) as exc_info:
        raise_for_domain_errors(
            operation="lms.chat",
            errors=[
                envelope_pb2.ErrorDetail(
                    code="INVALID_ARGUMENT",
                    message="prompt required",
                    category=envelope_pb2.ERROR_CATEGORY_VALIDATION,
                    retryable=False,
                )
            ],
        )

    assert exc_info.value.details[0].category == "validation"
    assert exc_info.value.details[0].code == "INVALID_ARGUMENT"
