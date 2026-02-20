"""Configuration model for the Qdrant substrate."""

from __future__ import annotations

from dataclasses import dataclass

from packages.brain_shared.embeddings import (
    SUPPORTED_DISTANCE_METRICS,
    SUPPORTED_DISTANCE_METRICS_TEXT,
)


@dataclass(frozen=True)
class QdrantConfig:
    """Runtime configuration required for Qdrant substrate access."""

    url: str
    timeout_seconds: float
    collection_name: str
    distance_metric: str

    def validate(self) -> None:
        """Validate required Qdrant substrate configuration invariants."""
        if not self.url:
            raise ValueError("qdrant.url is required")
        if self.timeout_seconds <= 0:
            raise ValueError("qdrant.timeout_seconds must be > 0")
        if not self.collection_name:
            raise ValueError("qdrant.collection_name is required")
        if self.distance_metric not in SUPPORTED_DISTANCE_METRICS:
            raise ValueError(
                f"qdrant.distance_metric must be one of: {SUPPORTED_DISTANCE_METRICS_TEXT}"
            )
