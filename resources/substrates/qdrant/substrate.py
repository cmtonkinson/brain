"""Transport-agnostic substrate contract for Qdrant operations."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict


class RetrievedPoint(BaseModel):
    """Retrieved Qdrant point data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: tuple[float, ...]
    payload: Mapping[str, object]


class SearchPoint(BaseModel):
    """Qdrant search result with score and payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float
    payload: Mapping[str, object]


class QdrantHealthStatus(BaseModel):
    """Qdrant substrate readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class QdrantSubstrate(Protocol):
    """Protocol for direct Qdrant substrate operations."""

    def health(self) -> QdrantHealthStatus:
        """Probe Qdrant substrate readiness."""

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
        """Delete one point by id, returning whether a delete was issued."""

    def search_points(
        self,
        *,
        filters: Mapping[str, str],
        query_vector: Sequence[float],
        limit: int,
    ) -> list[SearchPoint]:
        """Search points in the configured collection using exact-match filters."""
