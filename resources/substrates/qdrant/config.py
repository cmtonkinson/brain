"""Configuration model for the Qdrant substrate."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, model_validator
from packages.brain_shared.embeddings import (
    SUPPORTED_DISTANCE_METRICS,
    SUPPORTED_DISTANCE_METRICS_TEXT,
)


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
        if self.distance_metric not in SUPPORTED_DISTANCE_METRICS:
            raise ValueError(
                f"qdrant.distance_metric must be one of: {SUPPORTED_DISTANCE_METRICS_TEXT}"
            )
        return self
