"""Concrete Qdrant substrate implementation using qdrant-client."""

from __future__ import annotations

from threading import Lock
from typing import Iterable, Mapping, Sequence

from packages.brain_shared.embeddings import (
    DISTANCE_METRIC_COSINE,
    DISTANCE_METRIC_DOT,
    DISTANCE_METRIC_EUCLID,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from qdrant_client.http import models

from resources.substrates.qdrant.client import create_qdrant_client
from resources.substrates.qdrant.component import RESOURCE_COMPONENT_ID
from resources.substrates.qdrant.config import QdrantConfig
from resources.substrates.qdrant.substrate import (
    QdrantHealthStatus,
    QdrantSubstrate,
    RetrievedPoint,
    SearchPoint,
)

_LOGGER = get_logger(__name__)
_DISTANCE_MAPPING = {
    DISTANCE_METRIC_COSINE: models.Distance.COSINE,
    DISTANCE_METRIC_DOT: models.Distance.DOT,
    DISTANCE_METRIC_EUCLID: models.Distance.EUCLID,
}


class QdrantClientSubstrate(QdrantSubstrate):
    """Direct Qdrant substrate implementation for one configured collection."""

    def __init__(self, config: QdrantConfig) -> None:
        self._config = config
        self._client = create_qdrant_client(config)
        self._collection = config.collection_name
        self._lock = Lock()

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def health(self) -> QdrantHealthStatus:
        """Return substrate readiness based on client collection existence probe."""
        try:
            self._client.collection_exists(self._collection)
        except Exception as exc:  # noqa: BLE001
            return QdrantHealthStatus(
                ready=False,
                detail=f"qdrant probe failed: {type(exc).__name__}",
            )
        return QdrantHealthStatus(ready=True, detail="ok")

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def get_collection_vector_size(self) -> int | None:
        """Return configured collection vector size if collection exists."""
        if not self._collection_exists():
            return None

        collection = self._client.get_collection(self._collection)
        vectors = collection.config.params.vectors
        if isinstance(vectors, models.VectorParams):
            return int(vectors.size)
        return None

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("point_id",),
    )
    def upsert_point(
        self,
        *,
        point_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        """Insert or replace a point in the configured collection."""
        self._ensure_collection(len(vector))
        point = models.PointStruct(
            id=point_id,
            vector=list(vector),
            payload=dict(payload),
        )
        self._client.upsert(
            collection_name=self._collection,
            points=[point],
            wait=True,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("point_id",),
    )
    def retrieve_point(self, *, point_id: str) -> RetrievedPoint | None:
        """Fetch one point by id from the configured collection."""
        if not self._collection_exists():
            return None

        points = self._client.retrieve(
            collection_name=self._collection,
            ids=[point_id],
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            return None

        point = points[0]
        payload = point.payload if isinstance(point.payload, dict) else {}

        vector = point.vector
        vector_values: Iterable[float]
        if isinstance(vector, list):
            vector_values = vector
        elif isinstance(vector, dict):
            first = next(iter(vector.values()), [])
            vector_values = first if isinstance(first, list) else []
        else:
            vector_values = []

        return RetrievedPoint(
            vector=tuple(float(value) for value in vector_values),
            payload=dict(payload),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
        id_fields=("point_id",),
    )
    def delete_point(self, *, point_id: str) -> bool:
        """Delete one point by id, returning whether a delete was issued."""
        if not self._collection_exists():
            return False

        self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True,
        )
        return True

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(RESOURCE_COMPONENT_ID),
    )
    def search_points(
        self,
        *,
        filters: Mapping[str, str],
        query_vector: Sequence[float],
        limit: int,
    ) -> list[SearchPoint]:
        """Search points in the configured collection using exact-match filters."""
        if not self._collection_exists():
            return []

        must_conditions = [
            models.FieldCondition(key=key, match=models.MatchValue(value=value))
            for key, value in filters.items()
            if value
        ]

        results = self._client.search(
            collection_name=self._collection,
            query_vector=list(query_vector),
            query_filter=models.Filter(must=must_conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        points: list[SearchPoint] = []
        for point in results:
            payload = point.payload if isinstance(point.payload, dict) else {}
            points.append(
                SearchPoint(
                    score=float(point.score),
                    payload=dict(payload),
                )
            )
        return points

    def _collection_exists(self) -> bool:
        """Return True if the configured collection exists."""
        return bool(self._client.collection_exists(self._collection))

    def _ensure_collection(self, vector_size: int) -> None:
        """Create collection if absent using configured distance metric."""
        if self._collection_exists():
            return

        with self._lock:
            if self._collection_exists():
                return
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=_distance(self._config.distance_metric),
                ),
            )


def _distance(metric: str) -> models.Distance:
    """Map configured metric name to Qdrant distance enum."""
    return _DISTANCE_MAPPING[metric]
