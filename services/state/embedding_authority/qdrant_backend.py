"""EAS domain adapter over the Qdrant substrate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Mapping, Sequence

from resources.substrates.qdrant import QdrantClientSubstrate, QdrantConfig
from resources.substrates.qdrant.substrate import QdrantSubstrate
from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef
from services.state.embedding_authority.settings import EmbeddingSettings


class QdrantEmbeddingBackend:
    """EAS backend that maps embedding domain operations to Qdrant substrate calls."""

    def __init__(self, settings: EmbeddingSettings, substrate: QdrantSubstrate | None = None) -> None:
        self._substrate = substrate or QdrantClientSubstrate(
            QdrantConfig(
                url=settings.qdrant_url,
                timeout_seconds=settings.request_timeout_seconds,
                collection_name=settings.collection_name,
                distance_metric=settings.distance_metric,
            )
        )

    def upsert(
        self,
        *,
        ref: EmbeddingRef,
        vector: Sequence[float],
        model: str,
        metadata: dict[str, str],
    ) -> EmbeddingRecord:
        """Insert or replace an embedding record."""
        vector_size = len(vector)

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

        self._substrate.upsert_point(
            point_id=_point_id(ref),
            vector=vector,
            payload=payload,
        )

        return EmbeddingRecord(
            ref=ref,
            vector=tuple(float(value) for value in vector),
            model=model,
            dimensions=vector_size,
            metadata=dict(metadata),
            created_at=created_at,
            updated_at=now,
        )

    def get(self, *, ref: EmbeddingRef) -> EmbeddingRecord | None:
        """Fetch one embedding record by reference."""
        point = self._substrate.retrieve_point(point_id=_point_id(ref))
        if point is None:
            return None

        payload = point.payload
        metadata = payload.get("metadata") if isinstance(payload, dict) else {}
        metadata_map = dict(metadata) if isinstance(metadata, dict) else {}

        vector_tuple = tuple(float(value) for value in point.vector)

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
        return self._substrate.delete_point(point_id=_point_id(ref))

    def search(
        self,
        *,
        namespace: str,
        query_vector: Sequence[float],
        limit: int,
        model: str,
    ) -> list[EmbeddingMatch]:
        """Run nearest-neighbor search scoped to namespace and model."""
        filters: dict[str, str] = {"namespace": namespace}
        if model:
            filters["model"] = model

        results = self._substrate.search_points(
            filters=filters,
            query_vector=query_vector,
            limit=limit,
        )

        matches: list[EmbeddingMatch] = []
        for point in results:
            payload = point.payload if isinstance(point.payload, Mapping) else {}
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
        return self._substrate.get_collection_vector_size()


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
