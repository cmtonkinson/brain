"""Pydantic request-validation models for Object Authority Service API."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from packages.brain_shared.blob_validation import normalize_extension

_KEY_RE = re.compile(
    r"^(?P<version>[a-z0-9]+):(?P<algorithm>[a-z0-9]+):(?P<digest>[0-9a-f]{64})$"
)


class _ValidationModel(BaseModel):
    """Base request model with strict shape semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PutObjectRequest(_ValidationModel):
    """Validated put-object request shape."""

    content: bytes = Field()
    extension: str
    content_type: str
    original_filename: str
    source_uri: str

    @field_validator("extension")
    @classmethod
    def _validate_extension(cls, value: str) -> str:
        """Require and normalize extension token."""
        return normalize_extension(value=value)

    @field_validator("content_type", "original_filename", "source_uri")
    @classmethod
    def _normalize_optional_text(cls, value: str) -> str:
        """Normalize optional textual metadata fields."""
        return value.strip()


class ObjectKeyRequest(_ValidationModel):
    """Validated request shape for operations keyed by object key."""

    object_key: str

    @field_validator("object_key")
    @classmethod
    def _validate_object_key(cls, value: str, info: ValidationInfo) -> str:
        """Validate canonical object key shape and normalize to lowercase."""
        normalized = value.strip().lower()
        if normalized == "":
            raise ValueError(f"{info.field_name} is required")
        if _KEY_RE.match(normalized) is None:
            raise ValueError(
                f"{info.field_name} must match '<version>:<algorithm>:<64hex>'"
            )
        return normalized
