"""Shared validation helpers for blob/object storage identifiers."""

from __future__ import annotations


def normalize_extension(*, value: str, field_name: str = "extension") -> str:
    """Validate and normalize a filename extension token without leading dot."""
    normalized = value.strip().lstrip(".").lower()
    if normalized == "":
        raise ValueError(f"{field_name} is required")
    if not normalized.replace("-", "").replace("_", "").isalnum():
        raise ValueError(f"{field_name} must be alphanumeric, '-' or '_'")
    return normalized
