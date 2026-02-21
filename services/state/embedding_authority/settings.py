"""Configuration model for Embedding Authority Service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from packages.brain_shared.embeddings import (
    SUPPORTED_DISTANCE_METRICS,
    SUPPORTED_DISTANCE_METRICS_TEXT,
)


@dataclass(frozen=True)
class EmbeddingSettings:
    """Runtime settings for Qdrant access and service limits."""

    qdrant_url: str
    distance_metric: str
    request_timeout_seconds: float
    max_list_limit: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "EmbeddingSettings":
        """Build settings from merged application config mapping."""
        embedding = config.get("embedding", {}) if isinstance(config, Mapping) else {}

        instance = cls(
            qdrant_url=str(embedding.get("qdrant_url", "http://qdrant:6333")),
            distance_metric=str(embedding.get("distance_metric", "cosine")),
            request_timeout_seconds=float(
                embedding.get("request_timeout_seconds", 10.0)
            ),
            max_list_limit=int(embedding.get("max_list_limit", 500)),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate settings invariants required for EAS behavior."""
        if not self.qdrant_url:
            raise ValueError("embedding.qdrant_url is required")
        if self.distance_metric not in SUPPORTED_DISTANCE_METRICS:
            raise ValueError(
                f"embedding.distance_metric must be one of: {SUPPORTED_DISTANCE_METRICS_TEXT}"
            )
        if self.request_timeout_seconds <= 0:
            raise ValueError("embedding.request_timeout_seconds must be > 0")
        if self.max_list_limit <= 0:
            raise ValueError("embedding.max_list_limit must be > 0")
