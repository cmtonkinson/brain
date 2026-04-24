"""Configuration model for the Qdrant substrate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
from lib.shared.embeddings import (
    SUPPORTED_DISTANCE_METRICS,
    SUPPORTED_DISTANCE_METRICS_TEXT,
)


class QdrantSettings(BaseModel):
    """Qdrant connection defaults for substrate usage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = "http://qdrant:6333"
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    distance_metric: str = "cosine"

    @field_validator("distance_metric")
    @classmethod
    def _validate_distance_metric(cls, value: str) -> str:
        _require_distance_metric(
            value=value, field_path="substrate.qdrant.distance_metric"
        )
        return value


class QdrantConfig(BaseModel):
    """Runtime configuration required for Qdrant substrate access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    timeout_seconds: float = Field(gt=0)
    collection_name: str = Field(min_length=1)
    distance_metric: str

    @field_validator("distance_metric")
    @classmethod
    def _validate_distance_metric(cls, value: str) -> str:
        _require_distance_metric(value=value, field_path="qdrant.distance_metric")
        return value


def _require_distance_metric(*, value: str, field_path: str) -> None:
    """Raise when distance metric is outside the supported set."""
    if value not in SUPPORTED_DISTANCE_METRICS:
        raise ValueError(
            f"{field_path} must be one of: {SUPPORTED_DISTANCE_METRICS_TEXT}"
        )
