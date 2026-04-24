"""Unit tests for Brain SDK transport/domain error mapping."""

from __future__ import annotations

import pytest


def test_map_transport_error_marks_retryable_statuses() -> None:
    """503 transport failures should map to retryable transport errors."""
    from lib.sdk.errors import BrainTransportError, map_transport_error

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
    from lib.sdk.errors import BrainValidationError, raise_for_domain_errors

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


def test_sdk_exceptions_allow_traceback_assignment() -> None:
    """SDK exceptions must remain mutable enough for Python traceback wiring."""
    from lib.sdk.errors import BrainTransportError

    error = BrainTransportError(
        message="transport failed",
        operation="switchboard.poll_operator_instruction",
        status_code=504,
        retryable=True,
    )

    error.__traceback__ = None

    assert str(error) == "transport failed"


# ---------------------------------------------------------------------------
# _detail_from_dict
# ---------------------------------------------------------------------------


def test_detail_from_dict_extracts_all_fields_from_dict() -> None:
    """Full dict input should populate all SdkErrorDetail fields."""
    from lib.sdk.errors import _detail_from_dict

    detail = _detail_from_dict(
        {
            "code": "NOT_FOUND",
            "message": "missing",
            "category": "not_found",
            "retryable": True,
            "metadata": {"field": "id"},
        }
    )

    assert detail.code == "NOT_FOUND"
    assert detail.message == "missing"
    assert detail.category == "not_found"
    assert detail.retryable is True
    assert detail.metadata == {"field": "id"}


def test_detail_from_dict_defaults_missing_dict_keys() -> None:
    """Empty dict should produce safe defaults for all fields."""
    from lib.sdk.errors import _detail_from_dict

    detail = _detail_from_dict({})

    assert detail.code == ""
    assert detail.message == ""
    assert detail.category == "unspecified"
    assert detail.retryable is False
    assert detail.metadata == {}


def test_detail_from_dict_extracts_fields_from_object() -> None:
    """Object with attributes should be extracted via getattr."""
    from types import SimpleNamespace

    from lib.sdk.errors import _detail_from_dict

    obj = SimpleNamespace(
        code="CONFLICT",
        message="duplicate",
        category="conflict",
        retryable=False,
        metadata={"key": "val"},
    )
    detail = _detail_from_dict(obj)

    assert detail.code == "CONFLICT"
    assert detail.message == "duplicate"
    assert detail.category == "conflict"


def test_detail_from_dict_defaults_missing_attributes() -> None:
    """Bare object with no attributes should produce safe defaults."""
    from lib.sdk.errors import _detail_from_dict

    detail = _detail_from_dict(object())

    assert detail.code == ""
    assert detail.message == ""
    assert detail.category == "unspecified"
    assert detail.retryable is False


# ---------------------------------------------------------------------------
# raise_for_domain_errors — category dispatch
# ---------------------------------------------------------------------------


def test_raise_for_domain_errors_noop_for_empty_errors() -> None:
    """Empty errors list should not raise."""
    from lib.sdk.errors import raise_for_domain_errors

    raise_for_domain_errors(operation="test.op", errors=[])


@pytest.mark.parametrize(
    ("category", "expected_type_name"),
    [
        ("validation", "BrainValidationError"),
        ("conflict", "BrainConflictError"),
        ("not_found", "BrainNotFoundError"),
        ("policy", "BrainPolicyError"),
        ("dependency", "BrainDependencyError"),
        ("internal", "BrainInternalError"),
    ],
)
def test_raise_for_domain_errors_maps_category_to_typed_error(
    category: str, expected_type_name: str
) -> None:
    """Each known category should dispatch to its typed SDK error class."""
    from lib.sdk import errors as sdk_errors
    from lib.sdk.errors import raise_for_domain_errors

    expected_cls = getattr(sdk_errors, expected_type_name)
    with pytest.raises(expected_cls):
        raise_for_domain_errors(
            operation="test.op",
            errors=[{"code": "X", "message": "m", "category": category}],
        )


def test_raise_for_domain_errors_falls_back_to_brain_domain_error() -> None:
    """Unknown category should fall back to base BrainDomainError."""
    from lib.sdk.errors import BrainDomainError, raise_for_domain_errors

    with pytest.raises(BrainDomainError):
        raise_for_domain_errors(
            operation="test.op",
            errors=[{"code": "X", "message": "m", "category": "custom"}],
        )


def test_raise_for_domain_errors_joins_messages_from_multiple_errors() -> None:
    """Multiple errors should have messages joined by '; ' in the exception."""
    from lib.sdk.errors import BrainValidationError, raise_for_domain_errors

    with pytest.raises(BrainValidationError, match="first.*second") as exc_info:
        raise_for_domain_errors(
            operation="test.op",
            errors=[
                {"code": "A", "message": "first", "category": "validation"},
                {"code": "B", "message": "second", "category": "validation"},
            ],
        )

    assert len(exc_info.value.details) == 2
    assert "; " in str(exc_info.value)
