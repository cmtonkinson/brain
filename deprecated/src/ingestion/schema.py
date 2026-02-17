"""Schema and validation helpers for ingestion intake requests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator


class IngestionValidationError(ValueError):
    """Raised when ingestion request validation fails."""


class IngestionRequest(BaseModel):
    """Normalized ingestion request payload for intake submission."""

    model_config = ConfigDict(extra="forbid")

    source_type: str
    source_uri: str | None = None
    source_actor: str | None = None
    payload: bytes | str | None = None
    existing_object_key: str | None = None
    capture_time: datetime
    mime_type: str | None = None

    @model_validator(mode="after")
    def _validate_request(self) -> "IngestionRequest":
        """Validate required fields and cross-field constraints."""
        validate_ingestion_request(self)
        return self


class IngestionResponse(BaseModel):
    """Response payload for ingestion submissions."""

    model_config = ConfigDict(extra="forbid")

    ingestion_id: UUID


def validate_ingestion_request(request: IngestionRequest) -> None:
    """Validate ingestion request invariants with deterministic errors."""
    if not request.source_type.strip():
        raise IngestionValidationError("source_type is required")
    if request.capture_time.tzinfo is None:
        raise IngestionValidationError("capture_time must be timezone-aware")
    has_payload = request.payload is not None
    has_existing = request.existing_object_key is not None
    if has_payload == has_existing:
        raise IngestionValidationError(
            "exactly one of payload or existing_object_key must be provided"
        )


def parse_ingestion_request(payload: Any) -> IngestionRequest:
    """Parse and validate a raw ingestion request payload."""
    try:
        request = IngestionRequest.model_validate(payload)
    except ValidationError as exc:
        raise IngestionValidationError(str(exc)) from exc
    validate_ingestion_request(request)
    return request
