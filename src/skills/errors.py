"""Shared error types for skill runtime execution."""

from __future__ import annotations

from typing import Any


class SkillRuntimeError(Exception):
    """Base exception for skill runtime failures."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the runtime error with a code and details."""
        super().__init__(message)
        self.code = code
        self.details = details or {}


class SkillValidationError(SkillRuntimeError):
    """Raised when schema validation fails."""


class SkillPolicyError(SkillRuntimeError):
    """Raised when policy evaluation denies execution."""


class SkillExecutionError(SkillRuntimeError):
    """Raised when a skill adapter fails to execute."""
