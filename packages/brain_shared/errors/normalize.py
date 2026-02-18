"""Exception normalization utilities for shared error contracts."""

from __future__ import annotations

from . import codes
from .factories import dependency_error, internal_error, not_found_error, policy_error, validation_error
from .types import ErrorDetail


def exception_to_error(exc: Exception) -> ErrorDetail:
    """Normalize a Python exception into a shared ``ErrorDetail``.

    This mapping is intentionally conservative and generic. Services can layer
    domain-specific normalization before falling back to this function.
    """
    metadata = {"exception_type": type(exc).__name__}

    if isinstance(exc, ValueError):
        return validation_error(str(exc), code=codes.INVALID_ARGUMENT, metadata=metadata)

    if isinstance(exc, KeyError):
        return not_found_error(str(exc), code=codes.RESOURCE_NOT_FOUND, metadata=metadata)

    if isinstance(exc, PermissionError):
        return policy_error(str(exc), code=codes.PERMISSION_DENIED, metadata=metadata)

    if isinstance(exc, TimeoutError):
        return dependency_error(
            str(exc) or "dependency timeout",
            code=codes.DEPENDENCY_TIMEOUT,
            retryable=True,
            metadata=metadata,
        )

    if isinstance(exc, ConnectionError):
        return dependency_error(
            str(exc) or "dependency unavailable",
            code=codes.DEPENDENCY_UNAVAILABLE,
            retryable=True,
            metadata=metadata,
        )

    return internal_error(
        str(exc) or "unexpected exception",
        code=codes.UNEXPECTED_EXCEPTION,
        metadata=metadata,
    )
