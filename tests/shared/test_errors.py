"""Unit tests for shared error types, factories, and exception normalization."""

from __future__ import annotations

import dataclasses

import pytest

from lib.shared.errors import (
    ErrorCategory,
    ErrorDetail,
    codes,
    conflict_error,
    dependency_error,
    exception_to_error,
    internal_error,
    not_found_error,
    policy_error,
    validation_error,
)


# ---------------------------------------------------------------------------
# ErrorCategory enum
# ---------------------------------------------------------------------------


def test_error_category_members_are_strings() -> None:
    """Every ErrorCategory member value should be a plain lowercase string."""
    for member in ErrorCategory:
        assert isinstance(member.value, str)
        assert member.value == member.value.lower()


def test_error_category_has_expected_member_count() -> None:
    """ErrorCategory should have exactly 7 members."""
    assert len(ErrorCategory) == 7


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (ErrorCategory.UNSPECIFIED, "unspecified"),
        (ErrorCategory.VALIDATION, "validation"),
        (ErrorCategory.CONFLICT, "conflict"),
        (ErrorCategory.NOT_FOUND, "not_found"),
        (ErrorCategory.POLICY, "policy"),
        (ErrorCategory.DEPENDENCY, "dependency"),
        (ErrorCategory.INTERNAL, "internal"),
    ],
)
def test_error_category_member_values(member: ErrorCategory, value: str) -> None:
    """Each ErrorCategory member should map to its canonical string value."""
    assert member.value == value


# ---------------------------------------------------------------------------
# ErrorDetail dataclass
# ---------------------------------------------------------------------------


def test_error_detail_is_frozen() -> None:
    """ErrorDetail instances should be immutable."""
    detail = ErrorDetail(code="TEST", message="msg", category=ErrorCategory.INTERNAL)
    with pytest.raises(dataclasses.FrozenInstanceError):
        detail.code = "OTHER"  # type: ignore[misc]


def test_error_detail_default_retryable_is_false() -> None:
    """ErrorDetail.retryable should default to False."""
    detail = ErrorDetail(code="TEST", message="msg", category=ErrorCategory.INTERNAL)
    assert detail.retryable is False


def test_error_detail_default_metadata_is_empty_dict() -> None:
    """ErrorDetail.metadata should default to an empty dict, not None."""
    detail = ErrorDetail(code="TEST", message="msg", category=ErrorCategory.INTERNAL)
    assert detail.metadata == {}
    assert isinstance(detail.metadata, dict)


# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------


_ALL_CODE_NAMES = [
    name
    for name in dir(codes)
    if not name.startswith("_") and isinstance(getattr(codes, name), str)
]


@pytest.mark.parametrize("code_name", _ALL_CODE_NAMES)
def test_error_codes_are_uppercase_strings(code_name: str) -> None:
    """Every shared error code constant should be a non-empty uppercase string."""
    value = getattr(codes, code_name)
    assert isinstance(value, str)
    assert value != ""
    assert value == value.upper()


def test_error_codes_count() -> None:
    """Shared error codes module should define exactly 14 code constants."""
    assert len(_ALL_CODE_NAMES) == 14


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def test_validation_error_sets_category_and_default_code() -> None:
    """validation_error should use VALIDATION category and VALIDATION_ERROR code."""
    err = validation_error("bad input")
    assert err.category == ErrorCategory.VALIDATION
    assert err.code == codes.VALIDATION_ERROR
    assert err.message == "bad input"
    assert err.retryable is False


def test_not_found_error_sets_category_and_default_code() -> None:
    """not_found_error should use NOT_FOUND category and NOT_FOUND code."""
    err = not_found_error("missing")
    assert err.category == ErrorCategory.NOT_FOUND
    assert err.code == codes.NOT_FOUND
    assert err.retryable is False


def test_conflict_error_sets_category_and_default_code() -> None:
    """conflict_error should use CONFLICT category and CONFLICT code."""
    err = conflict_error("duplicate")
    assert err.category == ErrorCategory.CONFLICT
    assert err.code == codes.CONFLICT
    assert err.retryable is False


def test_policy_error_sets_category_and_default_code() -> None:
    """policy_error should use POLICY category and POLICY_VIOLATION code."""
    err = policy_error("denied")
    assert err.category == ErrorCategory.POLICY
    assert err.code == codes.POLICY_VIOLATION
    assert err.retryable is False


def test_dependency_error_sets_category_and_default_retryable() -> None:
    """dependency_error should default retryable=True."""
    err = dependency_error("timeout")
    assert err.category == ErrorCategory.DEPENDENCY
    assert err.code == codes.DEPENDENCY_FAILURE
    assert err.retryable is True


def test_dependency_error_respects_retryable_override() -> None:
    """dependency_error should honor an explicit retryable=False."""
    err = dependency_error("permanent", retryable=False)
    assert err.retryable is False


def test_internal_error_sets_category_and_default_code() -> None:
    """internal_error should use INTERNAL category and INTERNAL_ERROR code."""
    err = internal_error("boom")
    assert err.category == ErrorCategory.INTERNAL
    assert err.code == codes.INTERNAL_ERROR
    assert err.retryable is False


@pytest.mark.parametrize(
    "factory",
    [
        validation_error,
        not_found_error,
        conflict_error,
        policy_error,
        internal_error,
    ],
)
def test_factory_passes_custom_code(factory: object) -> None:
    """Every factory should propagate a caller-provided code kwarg."""
    err = factory("msg", code="CUSTOM_CODE")  # type: ignore[operator]
    assert err.code == "CUSTOM_CODE"


@pytest.mark.parametrize(
    "factory",
    [
        validation_error,
        not_found_error,
        conflict_error,
        policy_error,
        dependency_error,
        internal_error,
    ],
)
def test_factory_passes_metadata(factory: object) -> None:
    """Every factory should propagate caller-provided metadata."""
    err = factory("msg", metadata={"field": "value"})  # type: ignore[operator]
    assert err.metadata == {"field": "value"}
    assert isinstance(err.metadata, dict)


@pytest.mark.parametrize(
    "factory",
    [
        validation_error,
        not_found_error,
        conflict_error,
        policy_error,
        dependency_error,
        internal_error,
    ],
)
def test_factory_none_metadata_becomes_empty_dict(factory: object) -> None:
    """Every factory should normalize None metadata to an empty dict."""
    err = factory("msg")  # type: ignore[operator]
    assert err.metadata == {}


# ---------------------------------------------------------------------------
# exception_to_error normalization
# ---------------------------------------------------------------------------


def test_exception_to_error_maps_value_error_to_validation() -> None:
    """ValueError should map to INVALID_ARGUMENT with validation category."""
    err = exception_to_error(ValueError("bad"))
    assert err.category == ErrorCategory.VALIDATION
    assert err.code == codes.INVALID_ARGUMENT
    assert err.message == "bad"


def test_exception_to_error_maps_key_error_to_not_found() -> None:
    """KeyError should map to RESOURCE_NOT_FOUND with not_found category."""
    err = exception_to_error(KeyError("missing"))
    assert err.category == ErrorCategory.NOT_FOUND
    assert err.code == codes.RESOURCE_NOT_FOUND


def test_exception_to_error_maps_permission_error_to_policy() -> None:
    """PermissionError should map to PERMISSION_DENIED with policy category."""
    err = exception_to_error(PermissionError("nope"))
    assert err.category == ErrorCategory.POLICY
    assert err.code == codes.PERMISSION_DENIED


def test_exception_to_error_maps_timeout_error_to_dependency() -> None:
    """TimeoutError should map to DEPENDENCY_TIMEOUT, retryable=True."""
    err = exception_to_error(TimeoutError("slow"))
    assert err.category == ErrorCategory.DEPENDENCY
    assert err.code == codes.DEPENDENCY_TIMEOUT
    assert err.retryable is True


def test_exception_to_error_maps_connection_error_to_dependency() -> None:
    """ConnectionError should map to DEPENDENCY_UNAVAILABLE, retryable=True."""
    err = exception_to_error(ConnectionError("refused"))
    assert err.category == ErrorCategory.DEPENDENCY
    assert err.code == codes.DEPENDENCY_UNAVAILABLE
    assert err.retryable is True


def test_exception_to_error_maps_unknown_exception_to_internal() -> None:
    """Unrecognized exceptions should fall back to UNEXPECTED_EXCEPTION."""
    err = exception_to_error(RuntimeError("boom"))
    assert err.category == ErrorCategory.INTERNAL
    assert err.code == codes.UNEXPECTED_EXCEPTION
    assert err.message == "boom"


def test_exception_to_error_timeout_empty_message_fallback() -> None:
    """TimeoutError with empty message should use 'dependency timeout' fallback."""
    err = exception_to_error(TimeoutError(""))
    assert err.message == "dependency timeout"


def test_exception_to_error_connection_empty_message_fallback() -> None:
    """ConnectionError with empty message should use 'dependency unavailable' fallback."""
    err = exception_to_error(ConnectionError(""))
    assert err.message == "dependency unavailable"


def test_exception_to_error_unknown_empty_message_fallback() -> None:
    """Unknown exception with empty message should use 'unexpected exception' fallback."""
    err = exception_to_error(RuntimeError(""))
    assert err.message == "unexpected exception"


@pytest.mark.parametrize(
    ("exc", "expected_type"),
    [
        (ValueError("x"), "ValueError"),
        (KeyError("x"), "KeyError"),
        (PermissionError("x"), "PermissionError"),
        (TimeoutError("x"), "TimeoutError"),
        (ConnectionError("x"), "ConnectionError"),
        (RuntimeError("x"), "RuntimeError"),
    ],
)
def test_exception_to_error_includes_exception_type_in_metadata(
    exc: Exception, expected_type: str
) -> None:
    """All dispatch paths should include exception_type in metadata."""
    err = exception_to_error(exc)
    assert err.metadata["exception_type"] == expected_type
