"""Qdrant backend adapter for Embedding Authority Service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Iterable, Sequence

from qdrant_client import QdrantClient
from qdrant_client.http import models

from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef
from services.state.embedding_authority.settings import EmbeddingSettings


@dataclass(frozen=True)
class StoredEmbedding:
    """Backend persistence response payload for a stored embedding."""

    record: EmbeddingRecord


class QdrantEmbeddingBackend:
    """Backend adapter for storing and searching embeddings in Qdrant."""

    def __init__(self, settings: EmbeddingSettings) -> None:
        self._settings = settings
        self._client = QdrantClient(url=settings.qdrant_url, timeout=settings.request_timeout_seconds)
        self._collection = settings.collection_name
        self._lock = Lock()

    def upsert(
        self,
        *,
        ref: EmbeddingRef,
        vector: Sequence[float],
        model: str,
        metadata: dict[str, str],
    ) -> StoredEmbedding:
        """Insert or replace an embedding record."""
        vector_size = len(vector)
        self._ensure_collection(vector_size)

        now = _utc_now()
        existing = self.get(ref=ref)
        created_at = existing.created_at if existing is not None else now

        payload = {
            "namespace": ref.namespace,
            "key": ref.key,
            "model": model,
            "metadata": dict(metadata),
            "created_at": _iso(created_at),
            "updated_at": _iso(now),
        }

        point = models.PointStruct(
            id=_point_id(ref),
            vector=list(vector),
            payload=payload,
        )

        self._client.upsert(
            collection_name=self._collection,
            points=[point],
            wait=True,
        )

        return StoredEmbedding(
            record=EmbeddingRecord(
                ref=ref,
                vector=tuple(float(value) for value in vector),
                model=model,
                dimensions=vector_size,
                metadata=dict(metadata),
                created_at=created_at,
                updated_at=now,
            )
        )

    def get(self, *, ref: EmbeddingRef) -> EmbeddingRecord | None:
        """Fetch one embedding record by reference."""
        if not self._collection_exists():
            return None

        points = self._client.retrieve(
            collection_name=self._collection,
            ids=[_point_id(ref)],
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            return None

        point = points[0]
        payload = point.payload or {}
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        metadata_map = dict(metadata) if isinstance(metadata, dict) else {}

        vector = point.vector
        vector_values: Iterable[float]
        if isinstance(vector, list):
            vector_values = vector
        elif isinstance(vector, dict):
            first = next(iter(vector.values()), [])
            vector_values = first if isinstance(first, list) else []
        else:
            vector_values = []
        vector_tuple = tuple(float(value) for value in vector_values)

        return EmbeddingRecord(
            ref=ref,
            vector=vector_tuple,
            model=str(payload.get("model", "")) if isinstance(payload, dict) else "",
            dimensions=len(vector_tuple),
            metadata=metadata_map,
            created_at=_parse_iso(str(payload.get("created_at", ""))),
            updated_at=_parse_iso(str(payload.get("updated_at", ""))),
        )

    def delete(self, *, ref: EmbeddingRef) -> bool:
        """Delete one embedding record by reference."""
        if not self._collection_exists():
            return False

        existed = self.get(ref=ref) is not None
        if not existed:
            return False

        self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[_point_id(ref)]),
            wait=True,
        )
        return True

    def search(
        self,
        *,
        namespace: str,
        query_vector: Sequence[float],
        limit: int,
        model: str,
    ) -> list[EmbeddingMatch]:
        """Run nearest-neighbor search scoped to namespace and model."""
        if not self._collection_exists():
            return []

        must_conditions: list[models.FieldCondition] = [
            models.FieldCondition(key="namespace", match=models.MatchValue(value=namespace)),
        ]
        if model:
            must_conditions.append(models.FieldCondition(key="model", match=models.MatchValue(value=model)))

        results = self._client.search(
            collection_name=self._collection,
            query_vector=list(query_vector),
            query_filter=models.Filter(must=must_conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

        matches: list[EmbeddingMatch] = []
        for point in results:
            payload = point.payload or {}
            key = str(payload.get("key", "")) if isinstance(payload, dict) else ""
            metadata = payload.get("metadata") if isinstance(payload, dict) else {}
            metadata_map = dict(metadata) if isinstance(metadata, dict) else {}
            matches.append(
                EmbeddingMatch(
                    ref=EmbeddingRef(namespace=namespace, key=key),
                    score=float(point.score),
                    metadata=metadata_map,
                )
            )
        return matches

    def get_collection_vector_size(self) -> int | None:
        """Return configured collection vector size if collection exists."""
        if not self._collection_exists():
            return None

        collection = self._client.get_collection(self._collection)
        vectors = collection.config.params.vectors
        if isinstance(vectors, models.VectorParams):
            return int(vectors.size)
        return None

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
                    distance=_distance(self._settings.distance_metric),
                ),
            )


def _distance(metric: str) -> models.Distance:
    """Map config distance metric string to Qdrant distance enum."""
    mapping = {
        "cosine": models.Distance.COSINE,
        "dot": models.Distance.DOT,
        "euclid": models.Distance.EUCLID,
    }
    return mapping[metric]


def _point_id(ref: EmbeddingRef) -> str:
    """Build deterministic point identifier for namespace/key reference."""
    return f"{ref.namespace}:{ref.key}"


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    """Serialize datetime to ISO 8601."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _parse_iso(value: str) -> datetime:
    """Parse ISO 8601 datetime, falling back to current UTC."""
    if not value:
        return _utc_now()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except ValueError:
        return _utc_now()
