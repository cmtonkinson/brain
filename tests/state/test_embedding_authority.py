"""Behavior tests for Embedding Authority Service authority semantics."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping, Sequence

from packages.brain_shared.envelope import EnvelopeKind, new_meta
from packages.brain_shared.ids import generate_ulid_str
from services.state.embedding_authority.domain import (
    ChunkRecord,
    EmbeddingRecord,
    EmbeddingSpec,
    EmbeddingStatus,
    SearchEmbeddingMatch,
    SourceRecord,
    UpsertEmbeddingVectorInput,
)
from services.state.embedding_authority.implementation import (
    DefaultEmbeddingAuthorityService,
    _canonical_spec_string,
)
from services.state.embedding_authority.interfaces import IndexSearchPoint
from services.state.embedding_authority.settings import EmbeddingSettings


@dataclass
class _IndexUpsert:
    spec_id: str
    chunk_id: str


class FakeQdrantIndex:
    """In-memory derived-index simulation for service behavior tests."""

    def __init__(self) -> None:
        self.collections: dict[str, int] = {}
        self.points: set[tuple[str, str]] = set()
        self.payloads: dict[tuple[str, str], dict[str, object]] = {}
        self.upserts: list[_IndexUpsert] = []
        self.deletes: list[tuple[str, str]] = []

    def ensure_collection(self, *, spec_id: str, dimensions: int) -> None:
        existing = self.collections.get(spec_id)
        if existing is not None and existing != dimensions:
            raise ValueError("dimension mismatch")
        self.collections[spec_id] = dimensions

    def upsert_point(
        self,
        *,
        spec_id: str,
        chunk_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        del vector
        self.points.add((spec_id, chunk_id))
        self.payloads[(spec_id, chunk_id)] = dict(payload)
        self.upserts.append(_IndexUpsert(spec_id=spec_id, chunk_id=chunk_id))

    def delete_point(self, *, spec_id: str, chunk_id: str) -> bool:
        self.deletes.append((spec_id, chunk_id))
        if (spec_id, chunk_id) in self.points:
            self.points.remove((spec_id, chunk_id))
            self.payloads.pop((spec_id, chunk_id), None)
            return True
        return False

    def search_points(
        self,
        *,
        spec_id: str,
        source_id: str,
        query_vector: Sequence[float],
        limit: int,
    ) -> list[IndexSearchPoint]:
        del query_vector
        matches: list[IndexSearchPoint] = []
        for point_spec_id, chunk_id in sorted(self.points):
            if point_spec_id != spec_id:
                continue
            payload = self.payloads.get((point_spec_id, chunk_id), {})
            if source_id and str(payload.get("source_id", "")) != source_id:
                continue
            matches.append(IndexSearchPoint(score=1.0, payload=payload))
            if len(matches) >= limit:
                break
        return matches


class FailingDeleteQdrantIndex(FakeQdrantIndex):
    """Qdrant fake that raises on delete to exercise best-effort cleanup paths."""

    def delete_point(self, *, spec_id: str, chunk_id: str) -> bool:
        del spec_id, chunk_id
        raise RuntimeError("qdrant delete failed")


class FailingUpsertQdrantIndex(FakeQdrantIndex):
    """Qdrant fake that fails vector writes for dependency-path testing."""

    def upsert_point(
        self,
        *,
        spec_id: str,
        chunk_id: str,
        vector: Sequence[float],
        payload: Mapping[str, object],
    ) -> None:
        del spec_id, chunk_id, vector, payload
        raise RuntimeError("qdrant unavailable")


class FakeRepository:
    """In-memory authoritative store simulation for service behavior tests."""

    def __init__(self) -> None:
        self.specs: dict[str, EmbeddingSpec] = {}
        self.specs_by_hash: dict[bytes, str] = {}
        self.active_spec_id: str | None = None
        self.sources: dict[str, SourceRecord] = {}
        self.sources_key: dict[tuple[str, str, str], str] = {}
        self.chunks: dict[str, ChunkRecord] = {}
        self.chunk_key: dict[tuple[str, int], str] = {}
        self.embeddings: dict[tuple[str, str], EmbeddingRecord] = {}

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
        if hash_bytes in self.specs_by_hash:
            return self.specs[self.specs_by_hash[hash_bytes]]
        spec_id = generate_ulid_str()
        now = _now()
        spec = EmbeddingSpec(
            id=spec_id,
            provider=provider,
            name=name,
            version=version,
            dimensions=dimensions,
            hash=hash_bytes,
            canonical_string=canonical_string,
            created_at=now,
            updated_at=now,
        )
        self.specs[spec_id] = spec
        self.specs_by_hash[hash_bytes] = spec_id
        return spec

    def get_spec(self, *, spec_id: str) -> EmbeddingSpec | None:
        return self.specs.get(spec_id)

    def list_specs(self, *, limit: int) -> list[EmbeddingSpec]:
        del limit
        return list(self.specs.values())

    def list_spec_ids(self) -> list[str]:
        return list(self.specs.keys())

    def get_active_spec_id(self) -> str | None:
        return self.active_spec_id

    def set_active_spec(self, *, spec_id: str) -> None:
        self.active_spec_id = spec_id

    def upsert_source(
        self,
        *,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata: Mapping[str, str],
    ) -> SourceRecord:
        key = (canonical_reference, service, principal)
        now = _now()
        source_id = self.sources_key.get(key)
        if source_id is None:
            source_id = generate_ulid_str()
            self.sources_key[key] = source_id
            created_at = now
        else:
            created_at = self.sources[source_id].created_at

        record = SourceRecord(
            id=source_id,
            source_type=source_type,
            canonical_reference=canonical_reference,
            service=service,
            principal=principal,
            metadata=dict(metadata),
            created_at=created_at,
            updated_at=now,
        )
        self.sources[source_id] = record
        return record

    def get_source(self, *, source_id: str) -> SourceRecord | None:
        return self.sources.get(source_id)

    def list_sources(
        self,
        *,
        canonical_reference: str,
        service: str,
        principal: str,
        limit: int,
    ) -> list[SourceRecord]:
        rows = list(self.sources.values())
        if canonical_reference:
            rows = [
                row for row in rows if row.canonical_reference == canonical_reference
            ]
        if service:
            rows = [row for row in rows if row.service == service]
        if principal:
            rows = [row for row in rows if row.principal == principal]
        return rows[:limit]

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
        key = (source_id, chunk_ordinal)
        now = _now()
        chunk_id = self.chunk_key.get(key)
        if chunk_id is None:
            chunk_id = generate_ulid_str()
            self.chunk_key[key] = chunk_id
            created_at = now
        else:
            created_at = self.chunks[chunk_id].created_at

        row = ChunkRecord(
            id=chunk_id,
            source_id=source_id,
            chunk_ordinal=chunk_ordinal,
            reference_range=reference_range,
            content_hash=content_hash,
            text=text,
            metadata=dict(metadata),
            created_at=created_at,
            updated_at=now,
        )
        self.chunks[chunk_id] = row
        return row

    def get_chunk(self, *, chunk_id: str) -> ChunkRecord | None:
        return self.chunks.get(chunk_id)

    def list_chunks_by_source(self, *, source_id: str, limit: int) -> list[ChunkRecord]:
        rows = [row for row in self.chunks.values() if row.source_id == source_id]
        rows.sort(key=lambda row: row.chunk_ordinal)
        return rows[:limit]

    def upsert_embedding(
        self,
        *,
        chunk_id: str,
        spec_id: str,
        content_hash: str,
        status: EmbeddingStatus,
        error_detail: str,
    ) -> EmbeddingRecord:
        key = (chunk_id, spec_id)
        now = _now()
        existing = self.embeddings.get(key)
        created_at = now if existing is None else existing.created_at
        row = EmbeddingRecord(
            chunk_id=chunk_id,
            spec_id=spec_id,
            content_hash=content_hash,
            status=status,
            error_detail=error_detail,
            created_at=created_at,
            updated_at=now,
        )
        self.embeddings[key] = row
        return row

    def get_embedding(self, *, chunk_id: str, spec_id: str) -> EmbeddingRecord | None:
        return self.embeddings.get((chunk_id, spec_id))

    def list_embeddings_by_source(
        self,
        *,
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        chunk_ids = {
            row.id for row in self.chunks.values() if row.source_id == source_id
        }
        rows = [
            row
            for row in self.embeddings.values()
            if row.chunk_id in chunk_ids and (not spec_id or row.spec_id == spec_id)
        ]
        return rows[:limit]

    def list_embeddings_by_status(
        self,
        *,
        status: EmbeddingStatus,
        spec_id: str,
        limit: int,
    ) -> list[EmbeddingRecord]:
        rows = [row for row in self.embeddings.values() if row.status == status]
        if spec_id:
            rows = [row for row in rows if row.spec_id == spec_id]
        return rows[:limit]

    def list_chunk_ids_for_source(self, *, source_id: str) -> list[str]:
        return [row.id for row in self.chunks.values() if row.source_id == source_id]

    def delete_chunk(self, *, chunk_id: str) -> bool:
        if chunk_id not in self.chunks:
            return False
        self.chunks.pop(chunk_id)
        for key in list(self.embeddings):
            if key[0] == chunk_id:
                self.embeddings.pop(key)
        return True

    def delete_source(self, *, source_id: str) -> bool:
        if source_id not in self.sources:
            return False
        self.sources.pop(source_id)
        for chunk_id in list(self.chunks):
            if self.chunks[chunk_id].source_id == source_id:
                self.delete_chunk(chunk_id=chunk_id)
        return True


def _now() -> datetime:
    return datetime.now(UTC)


def _meta() -> object:
    return new_meta(kind=EnvelopeKind.COMMAND, source="test", principal="operator")


def _service() -> tuple[
    DefaultEmbeddingAuthorityService, FakeRepository, FakeQdrantIndex
]:
    return _service_with()


def _service_with(
    *,
    repository: FakeRepository | None = None,
    index_backend: FakeQdrantIndex | None = None,
    max_list_limit: int = 100,
) -> tuple[DefaultEmbeddingAuthorityService, FakeRepository, FakeQdrantIndex]:
    """Build service with optional fake dependency overrides."""
    settings = EmbeddingSettings(
        qdrant_url="http://qdrant:6333",
        distance_metric="cosine",
        request_timeout_seconds=5.0,
        max_list_limit=max_list_limit,
    )
    resolved_repository = FakeRepository() if repository is None else repository
    resolved_index = FakeQdrantIndex() if index_backend is None else index_backend
    svc = DefaultEmbeddingAuthorityService(
        settings=settings,
        repository=resolved_repository,
        index_backend=resolved_index,
    )
    return svc, resolved_repository, resolved_index


def _create_active_spec(svc: DefaultEmbeddingAuthorityService) -> EmbeddingSpec:
    created = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    assert created.payload is not None
    activated = svc.set_active_spec(meta=_meta(), spec_id=created.payload.id)
    assert activated.payload is not None
    return activated.payload


def test_canonical_spec_serialization_and_hash_is_deterministic() -> None:
    """Canonical serialization and SHA-256 hash must be deterministic."""
    canonical = _canonical_spec_string(
        provider=" Ollama ",
        name="Nomic Embed Text",
        version="V1!",
        dimensions=768,
    )
    assert canonical == "ollama:nomicembedtext:v1:768"
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    assert len(digest) == 32


def test_upsert_spec_and_set_active_spec() -> None:
    """Specs should be created idempotently and persisted as active when requested."""
    svc, repository, index = _service()

    created = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    assert created.ok
    assert created.payload is not None

    duplicate = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    assert duplicate.payload is not None
    assert duplicate.payload.id == created.payload.id

    active = svc.set_active_spec(meta=_meta(), spec_id=created.payload.id)
    assert active.ok
    assert active.payload is not None
    assert repository.active_spec_id == created.payload.id
    assert index.collections[created.payload.id] == created.payload.dimensions


def test_get_active_spec_returns_not_found_when_unset() -> None:
    """No persisted active spec should return a not-found error."""
    svc, _, _ = _service()
    result = svc.get_active_spec(meta=_meta())
    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "not_found"


def test_chunk_id_stability_for_same_source_and_ordinal() -> None:
    """Repeated upsert_chunk for same source/ordinal must keep chunk_id stable."""
    svc, _, _ = _service()
    _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://1",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    source_id = source.payload.id

    first = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="1-10",
        content_hash="h1",
        text="hello",
        metadata={},
    )
    second = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="1-12",
        content_hash="h2",
        text="hello world",
        metadata={},
    )

    assert first.payload is not None
    assert second.payload is not None
    assert first.payload.id == second.payload.id


def test_upsert_chunk_does_not_implicitly_create_embedding() -> None:
    """Chunk upsert should not create embedding rows until vectors are provided."""
    svc, repository, _ = _service()
    _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://chunk-only",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None

    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="1",
        content_hash="hash",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None
    assert repository.embeddings == {}


def test_vector_upsert_creates_embedding_and_search_match() -> None:
    """Vector upsert should index a point and make it retrievable via search."""
    svc, _, _ = _service()
    spec = _create_active_spec(svc)

    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://search-1",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None

    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="a",
        content_hash="h-a",
        text="alpha",
        metadata={},
    )
    assert chunk.payload is not None

    upserted = svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=spec.id,
        vector=[0.1] * spec.dimensions,
    )
    assert upserted.ok
    assert upserted.payload is not None
    assert upserted.payload.status == EmbeddingStatus.INDEXED

    result = svc.search_embeddings(
        meta=_meta(),
        query_vector=[0.1] * spec.dimensions,
        source_id=source.payload.id,
        spec_id="",
        limit=10,
    )
    assert result.ok
    assert result.payload is not None
    assert len(result.payload) == 1

    match: SearchEmbeddingMatch = result.payload[0]
    assert match.chunk_id == chunk.payload.id
    assert match.source_id == source.payload.id


def test_vector_upsert_dimension_mismatch_is_validation_error() -> None:
    """Vector writes with wrong dimensions must fail validation."""
    svc, _, _ = _service()
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://dim",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None

    result = svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=spec.id,
        vector=[0.1, 0.2],
    )
    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "validation"


def test_batch_vector_upsert_aggregates_rows() -> None:
    """Batch vector upserts should return indexed rows for each successful item."""
    svc, _, _ = _service()
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://batch",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None

    first = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="a",
        content_hash="h1",
        text="a",
        metadata={},
    )
    second = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=2,
        reference_range="b",
        content_hash="h2",
        text="b",
        metadata={},
    )
    assert first.payload is not None
    assert second.payload is not None

    result = svc.upsert_embedding_vectors(
        meta=_meta(),
        items=[
            UpsertEmbeddingVectorInput(
                chunk_id=first.payload.id,
                spec_id=spec.id,
                vector=[0.1] * spec.dimensions,
            ),
            UpsertEmbeddingVectorInput(
                chunk_id=second.payload.id,
                spec_id=spec.id,
                vector=[0.2] * spec.dimensions,
            ),
        ],
    )
    assert result.ok
    assert result.payload is not None
    assert len(result.payload) == 2


def test_vector_upsert_dependency_failure_marks_embedding_failed(
    caplog: object,
) -> None:
    """Qdrant write failures should be surfaced and persisted as FAILED rows."""
    svc, repository, _ = _service_with(index_backend=FailingUpsertQdrantIndex())
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://qdrant-fail",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        result = svc.upsert_embedding_vector(
            meta=_meta(),
            chunk_id=chunk.payload.id,
            spec_id=spec.id,
            vector=[0.1] * spec.dimensions,
        )

    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "dependency"
    failed = repository.get_embedding(chunk_id=chunk.payload.id, spec_id=spec.id)
    assert failed is not None
    assert failed.status == EmbeddingStatus.FAILED
    assert any("Vector upsert failed" in item.message for item in caplog.records)


def test_hard_delete_removes_rows_and_best_effort_qdrant_delete() -> None:
    """Delete source should remove authoritative rows and invoke Qdrant deletes."""
    svc, _, index = _service()
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://5",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None
    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=spec.id,
        vector=[0.1] * spec.dimensions,
    )

    chunk_id = chunk.payload.id
    deleted = svc.delete_source(meta=_meta(), source_id=source_id)
    assert deleted.ok
    assert deleted.payload is True

    assert not svc.get_source(meta=_meta(), source_id=source_id).ok
    assert not svc.get_chunk(meta=_meta(), chunk_id=chunk_id).ok
    assert any(chunk_id == deleted_chunk for _, deleted_chunk in index.deletes)


def test_best_effort_cleanup_failures_are_logged_for_source_delete(
    caplog: object,
) -> None:
    """Source delete should remain successful while logging derived cleanup failures."""
    svc, _, _ = _service_with(index_backend=FailingDeleteQdrantIndex())
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://cleanup-source",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    first = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r1",
        content_hash="h1",
        text="text1",
        metadata={},
    )
    assert first.payload is not None
    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=first.payload.id,
        spec_id=spec.id,
        vector=[0.1] * spec.dimensions,
    )

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        deleted = svc.delete_source(meta=_meta(), source_id=source_id)

    assert deleted.ok
    assert deleted.payload is True
    assert any(
        "Best-effort derived cleanup failed" in item.message for item in caplog.records
    )


def test_invalid_ulid_is_validation_error_not_transport_error() -> None:
    """Malformed ULIDs should produce domain validation errors."""
    svc, _, _ = _service()
    result = svc.get_source(meta=_meta(), source_id="not-a-ulid")
    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "validation"


def test_explicit_spec_reads_do_not_mutate_active_spec() -> None:
    """Explicit spec reads must not mutate in-memory active-spec defaults."""
    svc, repository, _ = _service()
    first = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    second = svc.upsert_spec(
        meta=_meta(),
        provider="openai",
        name="text-embedding-3-large",
        version="v1",
        dimensions=8,
    )
    assert first.payload is not None
    assert second.payload is not None

    active = svc.set_active_spec(meta=_meta(), spec_id=first.payload.id)
    assert active.payload is not None
    assert repository.active_spec_id == first.payload.id

    # Force explicit-spec resolution path.
    _ = svc.get_embedding(
        meta=_meta(),
        chunk_id=generate_ulid_str(),
        spec_id=second.payload.id,
    )

    resolved = svc.get_active_spec(meta=_meta())
    assert resolved.payload is not None
    assert resolved.payload.id == first.payload.id


def test_list_embeddings_by_source_spec_filter_is_optional() -> None:
    """Source listing should not default to active spec when spec_id is empty."""
    svc, _, _ = _service()
    spec_a = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    spec_b = svc.upsert_spec(
        meta=_meta(),
        provider="openai",
        name="text-embedding-3-large",
        version="v1",
        dimensions=8,
    )
    assert spec_a.payload is not None
    assert spec_b.payload is not None

    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://optional-source-filter",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None

    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=spec_a.payload.id,
        vector=[0.1] * spec_a.payload.dimensions,
    )
    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=spec_b.payload.id,
        vector=[0.2] * spec_b.payload.dimensions,
    )

    all_specs = svc.list_embeddings_by_source(
        meta=_meta(),
        source_id=source.payload.id,
        spec_id="",
        limit=10,
    )
    assert all_specs.ok
    assert all_specs.payload is not None
    assert len(all_specs.payload) == 2

    only_a = svc.list_embeddings_by_source(
        meta=_meta(),
        source_id=source.payload.id,
        spec_id=spec_a.payload.id,
        limit=10,
    )
    assert only_a.ok
    assert only_a.payload is not None
    assert len(only_a.payload) == 1
    assert only_a.payload[0].spec_id == spec_a.payload.id


def test_list_embeddings_by_status_spec_filter_is_optional() -> None:
    """Status listing should support all-spec queries when spec_id is empty."""
    svc, _, _ = _service()
    spec_a = svc.upsert_spec(
        meta=_meta(),
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
    )
    spec_b = svc.upsert_spec(
        meta=_meta(),
        provider="openai",
        name="text-embedding-3-large",
        version="v1",
        dimensions=8,
    )
    assert spec_a.payload is not None
    assert spec_b.payload is not None

    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://optional-status-filter",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None

    first_chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r1",
        content_hash="h1",
        text="text1",
        metadata={},
    )
    second_chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=2,
        reference_range="r2",
        content_hash="h2",
        text="text2",
        metadata={},
    )
    assert first_chunk.payload is not None
    assert second_chunk.payload is not None

    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=first_chunk.payload.id,
        spec_id=spec_a.payload.id,
        vector=[0.1] * spec_a.payload.dimensions,
    )
    svc.upsert_embedding_vector(
        meta=_meta(),
        chunk_id=second_chunk.payload.id,
        spec_id=spec_b.payload.id,
        vector=[0.2] * spec_b.payload.dimensions,
    )

    all_specs = svc.list_embeddings_by_status(
        meta=_meta(),
        status=EmbeddingStatus.INDEXED,
        spec_id="",
        limit=10,
    )
    assert all_specs.ok
    assert all_specs.payload is not None
    assert len(all_specs.payload) == 2

    only_b = svc.list_embeddings_by_status(
        meta=_meta(),
        status=EmbeddingStatus.INDEXED,
        spec_id=spec_b.payload.id,
        limit=10,
    )
    assert only_b.ok
    assert only_b.payload is not None
    assert len(only_b.payload) == 1
    assert only_b.payload[0].spec_id == spec_b.payload.id


def test_get_embedding_without_active_spec_returns_not_found() -> None:
    """Embedding read without explicit spec should fail when active spec is unset."""
    svc, _, _ = _service()
    chunk_id = generate_ulid_str()

    result = svc.get_embedding(meta=_meta(), chunk_id=chunk_id, spec_id="")

    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "not_found"
    assert "active spec not set" in result.errors[0].message


def test_get_embedding_with_unknown_spec_returns_not_found() -> None:
    """Embedding read should fail when explicit spec id does not exist."""
    svc, _, _ = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://missing-spec",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None

    result = svc.get_embedding(
        meta=_meta(),
        chunk_id=chunk.payload.id,
        spec_id=generate_ulid_str(),
    )

    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "not_found"
    assert "spec not found" in result.errors[0].message


def test_get_embedding_returns_not_found_when_row_missing() -> None:
    """Embedding read should return not-found when chunk/spec exist but row is absent."""
    svc, _, _ = _service()
    spec = _create_active_spec(svc)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://missing-embedding-row",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert source.payload is not None
    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source.payload.id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert chunk.payload is not None

    result = svc.get_embedding(meta=_meta(), chunk_id=chunk.payload.id, spec_id=spec.id)

    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "not_found"
    assert "embedding not found" in result.errors[0].message


def test_search_embeddings_requires_query_vector() -> None:
    """Search should reject empty query vectors with a validation error."""
    svc, _, _ = _service()
    _create_active_spec(svc)

    result = svc.search_embeddings(
        meta=_meta(),
        query_vector=[],
        source_id="",
        spec_id="",
        limit=10,
    )

    assert not result.ok
    assert result.payload == []
    assert result.errors
    assert result.errors[0].category.value == "validation"
    assert "query_vector is required" in result.errors[0].message


def test_search_embeddings_rejects_dimension_mismatch() -> None:
    """Search should validate query-vector dimensions against resolved spec."""
    svc, _, _ = _service()
    spec = _create_active_spec(svc)

    result = svc.search_embeddings(
        meta=_meta(),
        query_vector=[0.1] * (spec.dimensions - 1),
        source_id="",
        spec_id="",
        limit=10,
    )

    assert not result.ok
    assert result.payload == []
    assert result.errors
    assert result.errors[0].category.value == "validation"
    assert "query_vector dimension mismatch" in result.errors[0].message


def test_search_embeddings_rejects_invalid_optional_ulids() -> None:
    """Search should reject malformed optional ULID filters."""
    svc, _, _ = _service()
    _create_active_spec(svc)

    result = svc.search_embeddings(
        meta=_meta(),
        query_vector=[0.1] * 8,
        source_id="not-a-ulid",
        spec_id="",
        limit=10,
    )

    assert not result.ok
    assert result.payload == []
    assert result.errors
    assert result.errors[0].category.value == "validation"
    assert "source_id must be a valid ULID string" in result.errors[0].message


def test_list_sources_reports_meta_validation_failures() -> None:
    """List sources should fail validation when required metadata fields are missing."""
    svc, _, _ = _service()
    invalid_meta = new_meta(kind=EnvelopeKind.COMMAND, source="", principal="operator")

    result = svc.list_sources(
        meta=invalid_meta,
        canonical_reference="",
        service="",
        principal="",
        limit=10,
    )

    assert not result.ok
    assert result.payload == []
    assert result.errors
    assert result.errors[0].category.value == "validation"
    assert "metadata.source is required" in result.errors[0].message


def test_list_chunks_by_source_rejects_invalid_ulid() -> None:
    """Chunk listing should reject malformed source ULIDs with validation errors."""
    svc, _, _ = _service()

    result = svc.list_chunks_by_source(meta=_meta(), source_id="not-a-ulid", limit=10)

    assert not result.ok
    assert result.payload == []
    assert result.errors
    assert result.errors[0].category.value == "validation"
    assert "source_id must be a valid ULID string" in result.errors[0].message


def test_list_sources_clamps_limit_to_service_setting() -> None:
    """Source listing should clamp limit requests to configured service maximum."""
    svc, _, _ = _service_with(max_list_limit=2)
    for index in range(5):
        _ = svc.upsert_source(
            meta=_meta(),
            canonical_reference=f"doc://limit-{index}",
            source_type="note",
            service="ingestion",
            principal="operator",
            metadata={},
        )

    result = svc.list_sources(
        meta=_meta(),
        canonical_reference="",
        service="",
        principal="",
        limit=999,
    )

    assert result.ok
    assert result.payload is not None
    assert len(result.payload) == 2
