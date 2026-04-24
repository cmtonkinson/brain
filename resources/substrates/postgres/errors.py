"""Postgres/SQLAlchemy exception normalization helpers."""

from __future__ import annotations

from lib.shared.errors import (
    ErrorDetail,
    codes,
    conflict_error,
    dependency_error,
    internal_error,
)

_UNIQUE_VIOLATION_TYPE_NAME = "UniqueViolation"
_UNIQUE_VIOLATION_MESSAGE_TOKEN = "duplicate key value"
_OPERATIONAL_ERROR_TYPE_NAME = "OperationalError"
_TIMEOUT_MESSAGE_TOKEN = "timeout"
_INTERFACE_ERROR_TYPE_NAME = "InterfaceError"
_PROGRAMMING_ERROR_TYPE_NAME = "ProgrammingError"


def is_postgres_error(exc: Exception) -> bool:
    """Return whether one exception appears to originate from the Postgres stack."""
    module_name = type(exc).__module__
    return "sqlalchemy" in module_name or "psycopg" in module_name


def normalize_postgres_error(exc: Exception) -> ErrorDetail:
    """Map low-level DB exceptions into shared structured error semantics."""
    exc_type_name = type(exc).__name__
    message = str(exc)
    metadata = {codes.EXCEPTION_TYPE_KEY: exc_type_name}

    if (
        _UNIQUE_VIOLATION_TYPE_NAME in exc_type_name
        or _UNIQUE_VIOLATION_MESSAGE_TOKEN in message
    ):
        return conflict_error(
            "resource already exists",
            code=codes.ALREADY_EXISTS,
            metadata=metadata,
        )

    if _OPERATIONAL_ERROR_TYPE_NAME in exc_type_name or _TIMEOUT_MESSAGE_TOKEN in (
        message.lower()
    ):
        return dependency_error(
            "postgres unavailable",
            code=codes.DEPENDENCY_UNAVAILABLE,
            retryable=True,
            metadata=metadata,
        )

    if (
        _INTERFACE_ERROR_TYPE_NAME in exc_type_name
        or _PROGRAMMING_ERROR_TYPE_NAME in exc_type_name
    ):
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
