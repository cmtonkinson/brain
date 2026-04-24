"""Validation and normalization helpers for envelope metadata and requests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lib.shared.errors import ErrorDetail, codes, validation_error
from .meta import EnvelopeKind, EnvelopeMeta, _normalize_utc


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
    """Return a copy of metadata with UTC-normalized timestamp.

    Returns the same object when the timestamp is already UTC to avoid
    unnecessary allocation on the hot path.
    """
    if meta.timestamp.tzinfo is UTC:
        return meta
    return meta.model_copy(update={"timestamp": _normalize_utc(meta.timestamp)})


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


def validate_service_request(
    *,
    meta: EnvelopeMeta,
    model: type[BaseModel],
    payload: Mapping[str, Any],
) -> tuple[BaseModel | None, list[ErrorDetail]]:
    """Validate envelope metadata and one Pydantic request payload.

    Returns ``(validated_model, [])`` on success, or ``(None, errors)`` on
    failure.  All Pydantic validation errors are surfaced — not just the first.
    """
    try:
        validate_meta(meta)
        request = model.model_validate(payload)
    except ValidationError as exc:
        errors: list[ErrorDetail] = []
        for err in exc.errors():
            field = ".".join(str(part) for part in err.get("loc", ()))
            field_label = field if field else "payload"
            message = f"{field_label}: {err.get('msg', 'invalid value')}"
            errors.append(validation_error(message, code=codes.INVALID_ARGUMENT))
        return None, errors
    except ValueError as exc:
        return None, [validation_error(str(exc), code=codes.INVALID_ARGUMENT)]

    return request, []
