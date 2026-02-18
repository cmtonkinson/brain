"""Private internal interfaces for Embedding Authority composition.

These protocols define dependency contracts the service can rely on without
coupling API-layer code to a specific backend adapter.
"""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from packages.brain_shared.envelope import EnvelopeMeta, Result
from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef


class EmbeddingCommandAdapter(Protocol):
    """Mutation contract for embedding storage operations."""

    def upsert(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
        vector: Sequence[float],
        model: str,
        metadata: Mapping[str, str],
    ) -> Result[EmbeddingRecord]:
        """Persist or replace an embedding record."""

    def delete(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
        missing_ok: bool,
    ) -> Result[bool]:
        """Delete an embedding record by reference."""


class EmbeddingQueryAdapter(Protocol):
    """Read/search contract for embedding retrieval operations."""

    def get(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
    ) -> Result[EmbeddingRecord]:
        """Fetch a single embedding record by reference."""

    def search(
        self,
        *,
        meta: EnvelopeMeta,
        namespace: str,
        query_vector: Sequence[float],
        limit: int,
        model: str,
    ) -> Result[list[EmbeddingMatch]]:
        """Return nearest-neighbor matches for the query vector."""
