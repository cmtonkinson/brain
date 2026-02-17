"""Validation types for commitment creation inputs."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from commitments.constants import COMMITMENT_STATES


class CommitmentCreationInput(BaseModel):
    """Validated input payload for commitment creation."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(..., min_length=1)
    state: str = Field(default="OPEN")
    importance: int = Field(default=2, ge=1, le=3)
    effort_provided: int = Field(default=2, ge=1, le=3)
    due_by: date | datetime | None = None
    effort_inferred: int | None = None
    provenance_id: UUID | None = None
    metadata: Any | None = None

    @field_validator("description")
    @classmethod
    def _normalize_description(cls, value: str) -> str:
        """Ensure descriptions are non-empty once whitespace is trimmed."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("description must be a non-empty string")
        return normalized

    @field_validator("state")
    @classmethod
    def _validate_state(cls, value: str) -> str:
        """Ensure state values match the supported commitment states."""
        normalized = value.strip()
        if normalized not in COMMITMENT_STATES:
            raise ValueError("state must be one of OPEN, COMPLETED, MISSED, CANCELED")
        return normalized


def validate_commitment_creation(
    payload: CommitmentCreationInput | dict,
) -> CommitmentCreationInput:
    """Normalize and validate commitment creation inputs."""
    if isinstance(payload, CommitmentCreationInput):
        return payload
    return CommitmentCreationInput.model_validate(payload)


__all__ = ["CommitmentCreationInput", "ValidationError", "validate_commitment_creation"]
