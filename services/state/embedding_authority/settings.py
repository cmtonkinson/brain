"""Configuration model for Embedding Authority Service."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EmbeddingSettings:
    """Runtime settings for active embedding spec and Qdrant access."""

    provider: str
    name: str
    version: str
    dimensions: int
    qdrant_url: str
    distance_metric: str
    request_timeout_seconds: float
    max_list_limit: int
    repair_batch_limit: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "EmbeddingSettings":
        """Build settings from merged application config mapping."""
        embedding = config.get("embedding", {}) if isinstance(config, Mapping) else {}

        instance = cls(
            provider=str(embedding.get("provider", "ollama")),
            name=str(embedding.get("name", "nomic-embed-text")),
            version=str(embedding.get("version", "v1")),
            dimensions=int(embedding.get("dimensions", 768)),
            qdrant_url=str(embedding.get("qdrant_url", "http://qdrant:6333")),
            distance_metric=str(embedding.get("distance_metric", "cosine")),
            request_timeout_seconds=float(embedding.get("request_timeout_seconds", 10.0)),
            max_list_limit=int(embedding.get("max_list_limit", 500)),
            repair_batch_limit=int(embedding.get("repair_batch_limit", 500)),
        )
        instance.validate()
        return instance

    def validate(self) -> None:
        """Validate settings invariants required for EAS behavior."""
        if not self.provider:
            raise ValueError("embedding.provider is required")
        if not self.name:
            raise ValueError("embedding.name is required")
        if not self.version:
            raise ValueError("embedding.version is required")
        if self.dimensions <= 0:
            raise ValueError("embedding.dimensions must be > 0")
        if not self.qdrant_url:
            raise ValueError("embedding.qdrant_url is required")
        if self.distance_metric not in {"cosine", "dot", "euclid"}:
            raise ValueError("embedding.distance_metric must be one of: cosine, dot, euclid")
        if self.request_timeout_seconds <= 0:
            raise ValueError("embedding.request_timeout_seconds must be > 0")
        if self.max_list_limit <= 0:
            raise ValueError("embedding.max_list_limit must be > 0")
        if self.repair_batch_limit <= 0:
            raise ValueError("embedding.repair_batch_limit must be > 0")
