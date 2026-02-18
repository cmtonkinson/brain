"""Private internal interfaces for Embedding Authority composition.

These protocols define internal dependency contracts used by the EAS
implementation. They are transport-agnostic and contain no gRPC/protobuf types.
"""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef


class EmbeddingBackend(Protocol):
    """Persistence/search backend contract for EAS internal composition."""

    def upsert(
        self,
        *,
        ref: EmbeddingRef,
        vector: Sequence[float],
        model: str,
        metadata: Mapping[str, str],
    ) -> EmbeddingRecord:
        """Persist or replace an embedding record."""

    def get(
        self,
        *,
        ref: EmbeddingRef,
    ) -> EmbeddingRecord | None:
        """Fetch a single embedding record by reference."""

    def delete(self, *, ref: EmbeddingRef) -> bool:
        """Delete an embedding record by reference."""

    def search(
        self,
        *,
        namespace: str,
        query_vector: Sequence[float],
        limit: int,
        model: str,
    ) -> list[EmbeddingMatch]:
        """Return nearest-neighbor matches for the query vector."""

    def get_collection_vector_size(self) -> int | None:
        """Return current collection vector size when available."""
