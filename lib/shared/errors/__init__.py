"""Public shared error API for Brain services."""

from . import codes
from .factories import (
    conflict_error,
    dependency_error,
    internal_error,
    not_found_error,
    policy_error,
    validation_error,
)
from .normalize import exception_to_error
from .types import ErrorCategory, ErrorDetail

__all__ = [
    "ErrorCategory",
    "ErrorDetail",
    "codes",
    "conflict_error",
    "dependency_error",
    "exception_to_error",
    "internal_error",
    "not_found_error",
    "policy_error",
    "validation_error",
]
