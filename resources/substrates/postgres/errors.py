"""Postgres/SQLAlchemy exception normalization helpers."""

from __future__ import annotations

from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    conflict_error,
    dependency_error,
    internal_error,
)


def normalize_postgres_error(exc: Exception) -> ErrorDetail:
    """Map low-level DB exceptions into shared structured error semantics."""
    exc_type_name = type(exc).__name__
    message = str(exc)
    metadata = {"exception_type": exc_type_name}

    if "UniqueViolation" in exc_type_name or "duplicate key value" in message:
        return conflict_error(
            "resource already exists",
            code=codes.ALREADY_EXISTS,
            metadata=metadata,
        )

    if "OperationalError" in exc_type_name or "timeout" in message.lower():
        return dependency_error(
            "postgres unavailable",
            code=codes.DEPENDENCY_UNAVAILABLE,
            retryable=True,
            metadata=metadata,
        )

    if "InterfaceError" in exc_type_name or "ProgrammingError" in exc_type_name:
        return dependency_error(
            "postgres request failed",
            code=codes.DEPENDENCY_FAILURE,
            retryable=False,
            metadata=metadata,
        )

    return internal_error(
        "unexpected postgres failure",
        code=codes.UNEXPECTED_EXCEPTION,
        metadata=metadata,
    )
