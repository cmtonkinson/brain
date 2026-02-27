"""Configuration model for the Qdrant substrate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator
from packages.brain_shared.embeddings import (
    SUPPORTED_DISTANCE_METRICS,
    SUPPORTED_DISTANCE_METRICS_TEXT,
)


class QdrantSettings(BaseModel):
    """Qdrant connection defaults for substrate usage."""

    url: str = "http://qdrant:6333"
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    distance_metric: str = "cosine"

    @model_validator(mode="after")
    def _validate_distance_metric(self) -> "QdrantSettings":
        """Validate supported distance metric names."""
        _validate_distance_metric(
            value=self.distance_metric,
            field_path="substrate.qdrant.distance_metric",
        )
        return self


class QdrantConfig(BaseModel):
    """Runtime configuration required for Qdrant substrate access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    timeout_seconds: float
    collection_name: str
    distance_metric: str

    @model_validator(mode="after")
    def _validate_fields(self) -> "QdrantConfig":
        """Validate required Qdrant substrate configuration invariants."""
        if self.url.strip() == "":
            raise ValueError("qdrant.url is required")
        if self.timeout_seconds <= 0:
            raise ValueError("qdrant.timeout_seconds must be > 0")
        if self.collection_name.strip() == "":
            raise ValueError("qdrant.collection_name is required")
        _validate_distance_metric(
            value=self.distance_metric,
            field_path="qdrant.distance_metric",
        )
        return self


def _validate_distance_metric(*, value: str, field_path: str) -> None:
    """Raise when distance metric is outside the supported set."""
    if value not in SUPPORTED_DISTANCE_METRICS:
        raise ValueError(
            f"{field_path} must be one of: {SUPPORTED_DISTANCE_METRICS_TEXT}"
        )
