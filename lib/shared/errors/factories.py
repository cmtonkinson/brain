"""Factory helpers for creating consistent shared errors."""

from __future__ import annotations

from typing import Mapping

from . import codes
from .types import ErrorCategory, ErrorDetail


def validation_error(
    message: str,
    *,
    code: str = codes.VALIDATION_ERROR,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create a validation-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.VALIDATION,
        retryable=False,
        metadata=_meta(metadata),
    )


def not_found_error(
    message: str,
    *,
    code: str = codes.NOT_FOUND,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create a not-found-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.NOT_FOUND,
        retryable=False,
        metadata=_meta(metadata),
    )


def conflict_error(
    message: str,
    *,
    code: str = codes.CONFLICT,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create a conflict-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.CONFLICT,
        retryable=False,
        metadata=_meta(metadata),
    )


def policy_error(
    message: str,
    *,
    code: str = codes.POLICY_VIOLATION,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create a policy-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.POLICY,
        retryable=False,
        metadata=_meta(metadata),
    )


def dependency_error(
    message: str,
    *,
    code: str = codes.DEPENDENCY_FAILURE,
    retryable: bool = True,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create a dependency-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.DEPENDENCY,
        retryable=retryable,
        metadata=_meta(metadata),
    )


def internal_error(
    message: str,
    *,
    code: str = codes.INTERNAL_ERROR,
    metadata: Mapping[str, str] | None = None,
) -> ErrorDetail:
    """Create an internal-category error."""
    return ErrorDetail(
        code=code,
        message=message,
        category=ErrorCategory.INTERNAL,
        retryable=False,
        metadata=_meta(metadata),
    )


def _meta(metadata: Mapping[str, str] | None) -> dict[str, str]:
    """Normalize optional metadata into a mutable plain dict."""
    if metadata is None:
        return {}
    return dict(metadata)
