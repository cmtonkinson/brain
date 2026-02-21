"""Qdrant-backed derived index operations for Embedding Authority Service."""

from __future__ import annotations

from threading import Lock
from typing import Mapping, Sequence

from resources.substrates.qdrant import QdrantClientSubstrate, QdrantConfig
from services.state.embedding_authority.interfaces import IndexSearchPoint


class QdrantEmbeddingBackend:
    """Per-spec Qdrant backend using one collection per embedding spec."""

    def __init__(
        self,
        *,
        qdrant_url: str,
        request_timeout_seconds: float,
        distance_metric: str,
    ) -> None:
        self._url = qdrant_url
        self._timeout_seconds = request_timeout_seconds
        self._distance_metric = distance_metric
        self._lock = Lock()
        self._substrates: dict[str, QdrantClientSubstrate] = {}

    def ensure_collection(self, *, spec_id: str, dimensions: int) -> None:
        """Ensure one collection exists with expected vector size."""
        substrate = self._substrate_for(spec_id)
        size = substrate.get_collection_vector_size()
        if size is None:
            # Upsert then delete one temporary point to force collection creation.
            temp_point_id = "__bootstrap__"
            substrate.upsert_point(
                point_id=temp_point_id,
                vector=[0.0 for _ in range(dimensions)],
                payload={},
            )
            substrate.delete_point(point_id=temp_point_id)
            return
        if size != dimensions:
            raise ValueError(
                f"qdrant collection '{spec_id}' dimension mismatch: expected {dimensions}, got {size}"
            )

    def upsert_point(
        self,
        *,
        spec_id: str,
        chunk_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        """Upsert one point in the spec collection."""
        self._substrate_for(spec_id).upsert_point(
            point_id=chunk_id,
            vector=vector,
            payload=payload,
        )

    def delete_point(self, *, spec_id: str, chunk_id: str) -> bool:
        """Delete one point from one spec collection."""
        return self._substrate_for(spec_id).delete_point(point_id=chunk_id)

    def search_points(
        self,
        *,
        spec_id: str,
        source_id: str,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[IndexSearchPoint]:
        """Search one spec collection and return normalized derived-index hits."""
        filters: dict[str, str] = {}
        if source_id:
            filters["source_id"] = source_id
        hits = self._substrate_for(spec_id).search_points(
            filters=filters,
            query_vector=query_vector,
            limit=limit,
        )
        return [
            IndexSearchPoint(score=item.score, payload=dict(item.payload))
            for item in hits
        ]

    def _substrate_for(self, spec_id: str) -> QdrantClientSubstrate:
        """Return cached substrate instance for one spec collection."""
        existing = self._substrates.get(spec_id)
        if existing is not None:
            return existing
        with self._lock:
            existing = self._substrates.get(spec_id)
            if existing is not None:
                return existing
            config = QdrantConfig(
                url=self._url,
                timeout_seconds=self._timeout_seconds,
                collection_name=spec_id,
                distance_metric=self._distance_metric,
            )
            substrate = QdrantClientSubstrate(config)
            self._substrates[spec_id] = substrate
            return substrate
