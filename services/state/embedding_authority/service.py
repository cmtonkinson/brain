"""Authoritative in-process Python API for Embedding Authority Service (EAS)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from packages.brain_shared.envelope import EnvelopeMeta, Result
from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef


class EmbeddingAuthorityService(ABC):
    """Transport-agnostic public contract for embedding operations.

    L1 callers should depend on this interface directly for east-west in-proc
    calls. Network transports (such as gRPC) adapt to this contract.
    """

    @abstractmethod
    def upsert_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
        vector: Sequence[float],
        model: str,
        metadata: Mapping[str, str],
    ) -> Result[EmbeddingRecord]:
        """Upsert one embedding record."""

    @abstractmethod
    def get_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
    ) -> Result[EmbeddingRecord]:
        """Read one embedding record."""

    @abstractmethod
    def delete_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
        missing_ok: bool,
    ) -> Result[bool]:
        """Delete one embedding record."""

    @abstractmethod
    def search_embeddings(
        self,
        *,
        meta: EnvelopeMeta,
        namespace: str,
        query_vector: Sequence[float],
        limit: int,
        model: str,
    ) -> Result[list[EmbeddingMatch]]:
        """Search embeddings by nearest-neighbor similarity."""
