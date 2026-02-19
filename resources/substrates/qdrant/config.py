"""Configuration model for the Qdrant substrate."""

from __future__ import annotations

from dataclasses import dataclass


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
        if self.distance_metric not in {"cosine", "dot", "euclid"}:
            raise ValueError(
                "qdrant.distance_metric must be one of: cosine, dot, euclid"
            )
