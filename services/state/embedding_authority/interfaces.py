"""Private dependency contracts used by EAS implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence

from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    SourceRecord,
)


@dataclass(frozen=True)
class IndexSearchPoint:
    """Derived index search hit returned from Qdrant-backed lookup."""

    score: float
    payload: Mapping[str, object]


class QdrantIndexBackend(Protocol):
    """Derived vector index backend contract."""

    def ensure_collection(self, *, spec_id: str, dimensions: int) -> None:
        """Ensure a per-spec collection exists for writes."""

    def upsert_point(
        self,
        *,
        spec_id: str,
        chunk_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        """Upsert one point in the spec collection."""

    def delete_point(self, *, spec_id: str, chunk_id: str) -> bool:
        """Delete one point from one spec collection."""

    def search_points(
        self,
        *,
        spec_id: str,
        source_id: str,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[IndexSearchPoint]:
        """Search points in one spec collection with optional source filter."""


class EmbeddingRepository(Protocol):
    """Authoritative Postgres repository contract for EAS state."""

    def upsert_spec(
        self,
        *,
        provider: str,
        name: str,
        version: str,
        dimensions: int,
        hash_bytes: bytes,
        canonical_string: str,
    ) -> EmbeddingSpec:
        """Ensure and return one authoritative spec row by unique hash."""

    def get_spec(self, *, spec_id: str) -> EmbeddingSpec | None:
        """Fetch one spec by id."""

    def list_specs(self, *, limit: int) -> list[EmbeddingSpec]:
        """List spec rows in descending recency order."""

    def list_spec_ids(self) -> list[str]:
        """List all known spec ids."""

    def get_active_spec_id(self) -> str | None:
        """Read active spec id singleton from authoritative storage."""

    def set_active_spec(self, *, spec_id: str) -> None:
        """Persist active spec id singleton in authoritative storage."""

    def upsert_source(
        self,
        *,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata: Mapping[str, str],
    ) -> SourceRecord:
        """Create/update source row and return it."""

    def get_source(self, *, source_id: str) -> SourceRecord | None:
        """Fetch one source by id."""

    def list_sources(
        self,
        *,
        canonical_reference: str,
        service: str,
        principal: str,
        limit: int,
    ) -> list[SourceRecord]:
        """List sources by optional filters."""

    def upsert_chunk(
        self,
        *,
        source_id: str,
        chunk_ordinal: int,
        reference_range: str,
        content_hash: str,
        text: str,
        metadata: Mapping[str, str],
    ) -> ChunkRecord:
        """Create/update chunk row for (source_id, chunk_ordinal)."""

    def get_chunk(self, *, chunk_id: str) -> ChunkRecord | None:
        """Fetch one chunk by id."""

    def list_chunks_by_source(self, *, source_id: str, limit: int) -> list[ChunkRecord]:
        """List chunks for one source."""

    def upsert_embedding(
        self,
        *,
        chunk_id: str,
        spec_id: str,
        content_hash: str,
        status: EmbeddingStatus,
        error_detail: str,
    ) -> EmbeddingRecord:
        """Create/update one embedding row for (chunk_id, spec_id)."""

    def get_embedding(self, *, chunk_id: str, spec_id: str) -> EmbeddingRecord | None:
        """Fetch one embedding row."""

    def list_embeddings_by_source(
        self,
        *,
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        """List embeddings for one source and optional spec."""

    def list_embeddings_by_status(
        self,
        *,
        status: EmbeddingStatus,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        """List embeddings by status and optional spec."""

    def list_chunk_ids_for_source(self, *, source_id: str) -> list[str]:
        """List chunk ids owned by one source."""

    def delete_chunk(self, *, chunk_id: str) -> bool:
        """Delete chunk and associated embedding rows."""

    def delete_source(self, *, source_id: str) -> bool:
        """Delete source and all owned chunk/embedding rows."""
