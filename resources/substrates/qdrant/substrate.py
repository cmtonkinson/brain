"""Transport-agnostic substrate contract for Qdrant operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class RetrievedPoint:
    """Retrieved Qdrant point data."""

    vector: tuple[float, ...]
    payload: Mapping[str, object]


@dataclass(frozen=True)
class SearchPoint:
    """Qdrant search result with score and payload."""

    score: float
    payload: Mapping[str, object]


class QdrantSubstrate(Protocol):
    """Protocol for direct Qdrant substrate operations."""

    def get_collection_vector_size(self) -> int | None:
        """Return configured collection vector size if collection exists."""

    def upsert_point(
        self,
        *,
        point_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        """Insert or replace a point in the configured collection."""

    def retrieve_point(self, *, point_id: str) -> RetrievedPoint | None:
        """Fetch one point by id from the configured collection."""

    def delete_point(self, *, point_id: str) -> bool:
        """Delete one point by id, returning whether a point existed."""

    def search_points(
        self,
        *,
        filters: Mapping[str, str],
        query_vector: Sequence[float],
        limit: int,
    ) -> list[SearchPoint]:
        """Search points in the configured collection using exact-match filters."""
