"""Validation helpers shared by Relay inbound and outbound services."""

from __future__ import annotations

from pydantic import ValidationError

from lib.shared.errors import ErrorDetail, codes, validation_error


def strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


def validation_error_from_pydantic(exc: ValidationError) -> ErrorDetail:
    """Map first pydantic validation error into shared validation contract."""
    first_error = exc.errors()[0]
    location = first_error.get("loc") or ()
    field = str(location[0]) if len(location) > 0 else "payload"
    message = str(first_error.get("msg", "invalid payload"))
    return validation_error(f"{field}: {message}", code=codes.INVALID_ARGUMENT)
