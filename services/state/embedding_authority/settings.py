"""Configuration model for Embedding Authority Service implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class EmbeddingSettings:
    """Runtime settings for embedding operations and backend access."""

    request_timeout_seconds: float
    default_top_k: int
    max_top_k: int
    namespace_strategy: str
    collection_name: str
    distance_metric: str
    qdrant_url: str
    postgres_schema: str
    model_dimensions: dict[str, int]

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> "EmbeddingSettings":
        """Build settings from merged app configuration mapping."""
        embedding = config.get("embedding", {}) if isinstance(config, Mapping) else {}

        request_timeout_seconds = float(embedding.get("request_timeout_seconds", 10.0))
        default_top_k = int(embedding.get("default_top_k", 10))
        max_top_k = int(embedding.get("max_top_k", 100))
        namespace_strategy = str(embedding.get("namespace_strategy", "single_collection"))
        collection_name = str(embedding.get("collection_name", "brain_embeddings"))
        distance_metric = str(embedding.get("distance_metric", "cosine"))
        qdrant_url = str(embedding.get("qdrant_url", "http://qdrant:6333"))
        postgres_schema = str(embedding.get("postgres_schema", "state_embedding_authority"))

        raw_model_dimensions = embedding.get("model_dimensions", {})
        model_dimensions: dict[str, int] = {}
        if isinstance(raw_model_dimensions, Mapping):
            model_dimensions = {str(key): int(value) for key, value in raw_model_dimensions.items()}

        settings = cls(
            request_timeout_seconds=request_timeout_seconds,
            default_top_k=default_top_k,
            max_top_k=max_top_k,
            namespace_strategy=namespace_strategy,
            collection_name=collection_name,
            distance_metric=distance_metric,
            qdrant_url=qdrant_url,
            postgres_schema=postgres_schema,
            model_dimensions=model_dimensions,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Validate settings invariants required for correct service behavior."""
        if self.request_timeout_seconds <= 0:
            raise ValueError("embedding.request_timeout_seconds must be > 0")
        if self.default_top_k <= 0:
            raise ValueError("embedding.default_top_k must be > 0")
        if self.max_top_k <= 0:
            raise ValueError("embedding.max_top_k must be > 0")
        if self.default_top_k > self.max_top_k:
            raise ValueError("embedding.default_top_k must be <= embedding.max_top_k")
        if self.namespace_strategy != "single_collection":
            raise ValueError("embedding.namespace_strategy currently only supports 'single_collection'")
        if not self.collection_name:
            raise ValueError("embedding.collection_name is required")
        if not self.qdrant_url:
            raise ValueError("embedding.qdrant_url is required")
        if not self.postgres_schema:
            raise ValueError("embedding.postgres_schema is required")
        if self.distance_metric not in {"cosine", "dot", "euclid"}:
            raise ValueError("embedding.distance_metric must be one of: cosine, dot, euclid")
