"""Pydantic settings for Commitment Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.control.commitment.component import SERVICE_COMPONENT_ID


class CommitmentServiceSettings(BaseModel):
    """Commitment Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    autonomous_creation_confidence_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    autonomous_transition_confidence_threshold: float = Field(
        default=0.9, ge=0.0, le=1.0
    )
    default_timezone: str = Field(default="UTC", min_length=1)
    review_batch_key: str = Field(default="commitment-review", min_length=1)
    follow_up_capability_id: str = Field(
        default="commitment-run-miss-detection", min_length=1
    )
    dedupe_enabled: bool = Field(default=True)
    dedupe_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    dedupe_summary_max_words: int = Field(default=50, ge=10, le=200)
    extraction_enabled: bool = Field(default=True)
    extraction_min_confidence: float = Field(default=0.4, ge=0.0, le=1.0)
    extraction_max_candidates: int = Field(default=10, ge=1, le=50)
    extraction_reasoning_level: str = Field(default="quick")

    @field_validator("default_timezone")
    @classmethod
    def _normalize_timezone(cls, value: str) -> str:
        """Return stripped default timezone."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("default_timezone is required")
        return normalized


def resolve_commitment_service_settings(
    settings: CoreRuntimeSettings,
) -> CommitmentServiceSettings:
    """Resolve Commitment Service settings from ``service.commitment``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=CommitmentServiceSettings,
    )
