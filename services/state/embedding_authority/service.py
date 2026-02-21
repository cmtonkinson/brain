"""Authoritative in-process Python API for Embedding Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from packages.brain_shared.envelope import EnvelopeMeta, Result
from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    SearchEmbeddingMatch,
    SourceRecord,
    UpsertChunkInput,
    UpsertEmbeddingVectorInput,
)


class EmbeddingAuthorityService(ABC):
    """Public API for the Embedding Authority Service.

    This interface is authoritative for in-process calls. gRPC/protobuf adapters
    are layered on top for north-south transport.
    """

    @abstractmethod
    def upsert_spec(
        self,
        *,
        meta: EnvelopeMeta,
        provider: str,
        name: str,
        version: str,
        dimensions: int,
    ) -> Result[EmbeddingSpec]:
        """Create or return one embedding spec by canonical identity."""

    @abstractmethod
    def set_active_spec(
        self, *, meta: EnvelopeMeta, spec_id: str
    ) -> Result[EmbeddingSpec]:
        """Persist and return the active spec used for defaulted spec operations."""

    @abstractmethod
    def upsert_source(
        self,
        *,
        meta: EnvelopeMeta,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata: Mapping[str, str],
    ) -> Result[SourceRecord]:
        """Create or update one source."""

    @abstractmethod
    def upsert_chunk(
        self,
        *,
        meta: EnvelopeMeta,
        source_id: str,
        chunk_ordinal: int,
        reference_range: str,
        content_hash: str,
        text: str,
        metadata: Mapping[str, str],
    ) -> Result[ChunkRecord]:
        """Create or update one chunk."""

    @abstractmethod
    def upsert_chunks(
        self,
        *,
        meta: EnvelopeMeta,
        items: Sequence[UpsertChunkInput],
    ) -> Result[list[ChunkRecord]]:
        """Batch convenience API for chunk upserts."""

    @abstractmethod
    def upsert_embedding_vector(
        self,
        *,
        meta: EnvelopeMeta,
        chunk_id: str,
        spec_id: str,
        vector: Sequence[float],
    ) -> Result[EmbeddingRecord]:
        """Persist one vector point and indexed embedding status row."""

    @abstractmethod
    def upsert_embedding_vectors(
        self,
        *,
        meta: EnvelopeMeta,
        items: Sequence[UpsertEmbeddingVectorInput],
    ) -> Result[list[EmbeddingRecord]]:
        """Batch convenience API for vector upserts."""

    @abstractmethod
    def delete_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Result[bool]:
        """Hard-delete one chunk and derived embedding rows."""

    @abstractmethod
    def delete_source(self, *, meta: EnvelopeMeta, source_id: str) -> Result[bool]:
        """Hard-delete one source and all owned chunks/embeddings."""

    @abstractmethod
    def get_source(self, *, meta: EnvelopeMeta, source_id: str) -> Result[SourceRecord]:
        """Read one source by id."""

    @abstractmethod
    def list_sources(
        self,
        *,
        meta: EnvelopeMeta,
        canonical_reference: str,
        service: str,
        principal: str,
        limit: int,
    ) -> Result[list[SourceRecord]]:
        """List sources by optional filters."""

    @abstractmethod
    def get_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Result[ChunkRecord]:
        """Read one chunk by id."""

    @abstractmethod
    def list_chunks_by_source(
        self,
        *,
        meta: EnvelopeMeta,
        source_id: str,
        limit: int,
    ) -> Result[list[ChunkRecord]]:
        """List chunks for one source."""

    @abstractmethod
    def get_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        chunk_id: str,
        spec_id: str = "",
    ) -> Result[EmbeddingRecord]:
        """Read one embedding row; default ``spec_id`` is active spec."""

    @abstractmethod
    def list_embeddings_by_source(
        self,
        *,
        meta: EnvelopeMeta,
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> Result[list[EmbeddingRecord]]:
        """List embedding rows for chunks under one source."""

    @abstractmethod
    def list_embeddings_by_status(
        self,
        *,
        meta: EnvelopeMeta,
        status: EmbeddingStatus,
        spec_id: str,
        limit: int,
    ) -> Result[list[EmbeddingRecord]]:
        """List embedding rows by status, optionally scoped to one spec."""

    @abstractmethod
    def search_embeddings(
        self,
        *,
        meta: EnvelopeMeta,
        query_vector: Sequence[float],
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> Result[list[SearchEmbeddingMatch]]:
        """Search derived embeddings by semantic similarity."""

    @abstractmethod
    def get_active_spec(self, *, meta: EnvelopeMeta) -> Result[EmbeddingSpec]:
        """Return persisted active spec used for defaulted operations."""

    @abstractmethod
    def list_specs(
        self, *, meta: EnvelopeMeta, limit: int
    ) -> Result[list[EmbeddingSpec]]:
        """List known specs."""

    @abstractmethod
    def get_spec(self, *, meta: EnvelopeMeta, spec_id: str) -> Result[EmbeddingSpec]:
        """Read one spec by id."""
