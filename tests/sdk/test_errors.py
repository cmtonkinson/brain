"""Unit tests for Brain SDK transport/domain error mapping."""

from __future__ import annotations

import pytest


def test_map_transport_error_marks_retryable_statuses() -> None:
    """503 transport failures should map to retryable transport errors."""
    from packages.brain_sdk.errors import BrainTransportError, map_transport_error

    error = map_transport_error(
        operation="vault.get",
        status_code=503,
        message="down",
        retryable=True,
    )

    assert isinstance(error, BrainTransportError)
    assert error.retryable is True
    assert error.status_code == 503


def test_raise_for_domain_errors_raises_typed_category_error() -> None:
    """Validation response errors should map to ``BrainValidationError``."""
    from packages.brain_sdk.errors import BrainValidationError, raise_for_domain_errors

    with pytest.raises(BrainValidationError) as exc_info:
        raise_for_domain_errors(
            operation="lms.chat",
            errors=[
                {
                    "code": "INVALID_ARGUMENT",
                    "message": "prompt required",
                    "category": "validation",
                    "retryable": False,
                }
            ],
        )

    assert exc_info.value.details[0].category == "validation"
    assert exc_info.value.details[0].code == "INVALID_ARGUMENT"
