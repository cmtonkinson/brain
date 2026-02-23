"""Validation and normalization helpers for envelope metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .meta import EnvelopeKind, EnvelopeMeta


class _ValidatedEnvelopeMeta(BaseModel):
    """Validation-only envelope metadata model used by ``validate_meta``."""

    model_config = ConfigDict(extra="forbid")

    envelope_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    parent_id: str
    timestamp: datetime
    kind: EnvelopeKind
    source: str = Field(min_length=1)
    principal: str = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_kind(self) -> "_ValidatedEnvelopeMeta":
        """Reject unspecified envelope kinds."""
        if self.kind == EnvelopeKind.UNSPECIFIED:
            raise ValueError("metadata.kind must be specified")
        return self


def validate_meta(meta: EnvelopeMeta) -> None:
    """Validate required envelope metadata fields.

    Raises ``ValueError`` when required fields are missing.
    """
    try:
        _ValidatedEnvelopeMeta.model_validate(meta.model_dump(mode="python"))
    except ValidationError as exc:
        raise ValueError(_map_meta_validation_error(exc)) from None


def normalize_meta(meta: EnvelopeMeta) -> EnvelopeMeta:
    """Return a copy of metadata with UTC-normalized timestamp."""
    timestamp = meta.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)

    if timestamp is meta.timestamp:
        return meta

    return meta.model_copy(update={"timestamp": timestamp})


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


def _map_meta_validation_error(error: ValidationError) -> str:
    """Map Pydantic metadata validation failures to stable public messages."""
    first_error = error.errors()[0]
    location = first_error.get("loc", ())
    if not location:
        return str(first_error.get("msg", "invalid metadata"))

    field_name = str(location[0])
    if field_name in {"envelope_id", "trace_id", "timestamp", "source", "principal"}:
        return f"metadata.{field_name} is required"
    if field_name == "kind":
        return "metadata.kind must be specified"
    return str(first_error.get("msg", "invalid metadata"))
