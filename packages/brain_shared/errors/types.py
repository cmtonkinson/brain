"""Canonical shared error types for Brain services.

This module defines a transport-agnostic error taxonomy and shape used by all
L1 services for east-west calls and adapter boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class ErrorCategory(str, Enum):
    """High-level error categories shared across service boundaries."""

    UNSPECIFIED = "unspecified"
    VALIDATION = "validation"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"
    POLICY = "policy"
    DEPENDENCY = "dependency"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ErrorDetail:
    """Structured error object used in envelope/result responses."""

    code: str
    message: str
    category: ErrorCategory
    retryable: bool = False
    metadata: Mapping[str, str] = field(default_factory=dict)
