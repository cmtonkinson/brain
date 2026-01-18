"""Schema definitions for attention router notification envelopes."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class EnvelopeDecision(str, Enum):
    """Decision outcomes for envelope validation."""

    ACCEPT = "ACCEPT"
    LOG_ONLY = "LOG_ONLY"


class ProvenanceInput(BaseModel):
    """Normalized provenance input metadata for a notification."""

    model_config = ConfigDict(extra="forbid")

    input_type: str = Field(..., min_length=1)
    reference: str = Field(..., min_length=1)
    description: str | None = None

    @field_validator("input_type", "reference")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        """Normalize required string fields."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str | None) -> str | None:
        """Normalize optional descriptions."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("description must be non-empty when provided.")
        return normalized


class NotificationEnvelope(BaseModel):
    """Versioned wrapper for notification payload metadata."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(..., min_length=1)
    source_component: str = Field(..., min_length=1)
    origin_signal: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    provenance: list[ProvenanceInput] = Field(..., min_length=1)

    @field_validator("version", "source_component", "origin_signal")
    @classmethod
    def _strip_required_fields(cls, value: str) -> str:
        """Normalize required identifiers."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("Required fields must be non-empty strings.")
        return normalized


class EnvelopeValidationResult(BaseModel):
    """Result of validating a notification envelope payload."""

    model_config = ConfigDict(extra="forbid")

    decision: EnvelopeDecision
    errors: list[str]
    envelope: NotificationEnvelope | None = None


def validate_envelope_payload(payload: dict[str, Any]) -> EnvelopeValidationResult:
    """Validate a notification envelope payload for routing decisions."""
    try:
        envelope = NotificationEnvelope.model_validate(payload)
    except ValidationError as exc:
        return EnvelopeValidationResult(
            decision=EnvelopeDecision.LOG_ONLY,
            errors=[error["msg"] for error in exc.errors()],
            envelope=None,
        )
    return EnvelopeValidationResult(
        decision=EnvelopeDecision.ACCEPT,
        errors=[],
        envelope=envelope,
    )
