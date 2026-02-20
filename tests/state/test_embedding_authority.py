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


class FakeVectorizer:
    """Deterministic fake vectorizer for unit tests."""

    def embed(self, *, text: str, dimensions: int) -> tuple[float, ...]:
        return tuple(float((idx + len(text)) % 7) for idx in range(dimensions))


class FakeQdrantIndex:
    """In-memory derived-index simulation for service behavior tests."""

    def __init__(self) -> None:
        self.collections: dict[str, int] = {}
        self.points: set[tuple[str, str]] = set()
        self.payloads: dict[tuple[str, str], dict[str, object]] = {}
        self.upserts: list[_IndexUpsert] = []
        self.deletes: list[tuple[str, str]] = []

    def ensure_collection(self, *, spec_id: str, dimensions: int) -> None:
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

    def point_exists(self, *, spec_id: str, chunk_id: str) -> bool:
        return (spec_id, chunk_id) in self.points

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


class FailingVectorizer(FakeVectorizer):
    """Vectorizer fake that always fails to exercise error logging paths."""

    def embed(self, *, text: str, dimensions: int) -> tuple[float, ...]:
        del text, dimensions
        raise RuntimeError("vectorizer failed")


class FakeRepository:
    """In-memory authoritative store simulation for service behavior tests."""

    def __init__(self) -> None:
        self.specs: dict[str, EmbeddingSpec] = {}
        self.specs_by_hash: dict[bytes, str] = {}
        self.sources: dict[str, SourceRecord] = {}
        self.sources_key: dict[tuple[str, str, str], str] = {}
        self.chunks: dict[str, ChunkRecord] = {}
        self.chunk_key: dict[tuple[str, int], str] = {}
        self.embeddings: dict[tuple[str, str], EmbeddingRecord] = {}

    def ensure_spec(
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
    vectorizer: FakeVectorizer | None = None,
) -> tuple[DefaultEmbeddingAuthorityService, FakeRepository, FakeQdrantIndex]:
    """Build service with optional fake dependency overrides."""
    settings = EmbeddingSettings(
        provider="ollama",
        name="nomic-embed-text",
        version="v1",
        dimensions=8,
        qdrant_url="http://qdrant:6333",
        distance_metric="cosine",
        request_timeout_seconds=5.0,
        max_list_limit=100,
        repair_batch_limit=100,
    )
    resolved_repository = FakeRepository() if repository is None else repository
    resolved_index = FakeQdrantIndex() if index_backend is None else index_backend
    resolved_vectorizer = FakeVectorizer() if vectorizer is None else vectorizer
    svc = DefaultEmbeddingAuthorityService(
        settings=settings,
        repository=resolved_repository,
        index_backend=resolved_index,
        vectorizer=resolved_vectorizer,
    )
    return svc, resolved_repository, resolved_index


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


def test_boot_ensures_spec_and_qdrant_collection() -> None:
    """Service bootstrap must ensure active spec row and matching collection."""
    svc, repository, index = _service()
    active = svc.get_active_spec(meta=_meta())
    assert active.ok
    assert active.payload is not None
    assert active.payload.id in repository.specs
    assert index.collections.get(active.payload.id) == active.payload.dimensions


def test_chunk_id_stability_for_same_source_and_ordinal() -> None:
    """Repeated upsert_chunk for same source/ordinal must keep chunk_id stable."""
    svc, _, _ = _service()
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
    assert first.payload.chunk.id == second.payload.chunk.id


def test_upsert_semantics_content_hash_change_rewrites_qdrant() -> None:
    """Changed content_hash must update embedding row and re-upsert Qdrant point."""
    svc, _, index = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://2",
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
        reference_range="a",
        content_hash="hash-a",
        text="alpha",
        metadata={},
    )
    second = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="b",
        content_hash="hash-b",
        text="beta",
        metadata={},
    )

    assert first.payload is not None
    assert second.payload is not None
    assert second.payload.embedding.content_hash == "hash-b"

    chunk_id = second.payload.chunk.id
    active_spec = svc.get_active_spec(meta=_meta()).payload
    assert active_spec is not None

    writes = [
        row
        for row in index.upserts
        if row.spec_id == active_spec.id and row.chunk_id == chunk_id
    ]
    assert len(writes) >= 2


def test_read_apis_reflect_authoritative_state() -> None:
    """Read APIs should consistently return the repository-backed current state."""
    svc, _, _ = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://3",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={"a": "b"},
    )
    source_id = source.payload.id if source.payload else ""

    chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=7,
        reference_range="10-20",
        content_hash="hash-7",
        text="chunk text",
        metadata={"x": "y"},
    )
    chunk_id = chunk.payload.chunk.id if chunk.payload else ""

    assert svc.get_source(meta=_meta(), source_id=source_id).ok
    assert (
        len(
            svc.list_sources(
                meta=_meta(), canonical_reference="", service="", principal="", limit=50
            ).payload
            or []
        )
        == 1
    )
    assert svc.get_chunk(meta=_meta(), chunk_id=chunk_id).ok
    assert (
        len(
            svc.list_chunks_by_source(
                meta=_meta(), source_id=source_id, limit=50
            ).payload
            or []
        )
        == 1
    )
    assert svc.get_embedding(meta=_meta(), chunk_id=chunk_id).ok
    assert (
        len(
            svc.list_embeddings_by_source(
                meta=_meta(), source_id=source_id, spec_id="", limit=50
            ).payload
            or []
        )
        == 1
    )
    assert (
        len(
            svc.list_embeddings_by_status(
                meta=_meta(), status=EmbeddingStatus.INDEXED, spec_id="", limit=50
            ).payload
            or []
        )
        == 1
    )


def test_repair_detects_missing_qdrant_points() -> None:
    """Repair should re-upsert missing points for indexed embeddings."""
    svc, _, index = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://4",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    upsert = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert upsert.payload is not None

    active_spec = svc.get_active_spec(meta=_meta()).payload
    assert active_spec is not None
    index.points.remove((active_spec.id, upsert.payload.chunk.id))

    repaired = svc.repair_spec(meta=_meta(), spec_id=active_spec.id, limit=100)
    assert repaired.ok
    assert repaired.payload is not None
    assert repaired.payload.repaired >= 1
    assert (active_spec.id, upsert.payload.chunk.id) in index.points


def test_hard_delete_removes_rows_and_best_effort_qdrant_delete() -> None:
    """Delete source should remove authoritative rows and invoke Qdrant deletes."""
    svc, _, index = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://5",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    upsert = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert upsert.payload is not None

    chunk_id = upsert.payload.chunk.id
    deleted = svc.delete_source(meta=_meta(), source_id=source_id)
    assert deleted.ok
    assert deleted.payload is True

    assert not svc.get_source(meta=_meta(), source_id=source_id).ok
    assert not svc.get_chunk(meta=_meta(), chunk_id=chunk_id).ok
    assert any(chunk_id == deleted_chunk for _, deleted_chunk in index.deletes)


def test_best_effort_cleanup_failures_are_logged_for_chunk_delete(
    caplog: object,
) -> None:
    """Chunk delete should remain successful while logging derived cleanup failures."""
    svc, _, _ = _service_with(index_backend=FailingDeleteQdrantIndex())
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://cleanup-chunk",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    upsert = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert upsert.payload is not None
    chunk_id = upsert.payload.chunk.id

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        deleted = svc.delete_chunk(meta=_meta(), chunk_id=chunk_id)

    assert deleted.ok
    assert deleted.payload is True
    assert any(
        "Best-effort derived cleanup failed" in item.message for item in caplog.records
    )


def test_best_effort_cleanup_failures_are_logged_for_source_delete(
    caplog: object,
) -> None:
    """Source delete should remain successful while logging derived cleanup failures."""
    svc, _, _ = _service_with(index_backend=FailingDeleteQdrantIndex())
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
    second = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=2,
        reference_range="r2",
        content_hash="h2",
        text="text2",
        metadata={},
    )
    assert first.payload is not None
    assert second.payload is not None

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        deleted = svc.delete_source(meta=_meta(), source_id=source_id)

    assert deleted.ok
    assert deleted.payload is True
    assert any(
        "Best-effort derived cleanup failed" in item.message for item in caplog.records
    )


def test_failed_embedding_with_same_hash_is_retried_on_upsert() -> None:
    """A failed row for current hash must be retried, not no-op'd."""
    svc, repository, index = _service()
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://6",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    created = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="same-hash",
        text="text",
        metadata={},
    )
    assert created.payload is not None
    active_spec = svc.get_active_spec(meta=_meta()).payload
    assert active_spec is not None

    chunk_id = created.payload.chunk.id
    key = (chunk_id, active_spec.id)
    failed_row = repository.embeddings[key]
    repository.embeddings[key] = EmbeddingRecord(
        chunk_id=failed_row.chunk_id,
        spec_id=failed_row.spec_id,
        content_hash=failed_row.content_hash,
        status=EmbeddingStatus.FAILED,
        error_detail="boom",
        created_at=failed_row.created_at,
        updated_at=failed_row.updated_at,
    )

    before = len(index.upserts)
    retried = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="same-hash",
        text="text",
        metadata={},
    )
    assert retried.ok
    assert retried.payload is not None
    assert retried.payload.embedding.status == EmbeddingStatus.INDEXED
    assert len(index.upserts) > before


def test_materialization_failure_is_logged_and_recorded_as_failed(
    caplog: object,
) -> None:
    """Materialization errors should be logged and persisted as FAILED embeddings."""
    svc, _, _ = _service_with(vectorizer=FailingVectorizer())
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://vectorizer-fail",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        upsert = svc.upsert_chunk(
            meta=_meta(),
            source_id=source_id,
            chunk_ordinal=1,
            reference_range="r",
            content_hash="h",
            text="text",
            metadata={},
        )

    assert upsert.ok
    assert upsert.payload is not None
    assert upsert.payload.embedding.status == EmbeddingStatus.FAILED
    assert any(
        "Embedding materialization failed" in item.message for item in caplog.records
    )


def test_repair_failure_is_logged_and_returned_as_dependency_error(
    caplog: object,
) -> None:
    """Repair failures should emit logs and return dependency-category errors."""

    class _FailingPointExistsBackend(FakeQdrantIndex):
        def point_exists(self, *, spec_id: str, chunk_id: str) -> bool:
            del spec_id, chunk_id
            raise RuntimeError("qdrant unavailable")

    failing_backend = _FailingPointExistsBackend()
    svc, _, _ = _service_with(index_backend=failing_backend)
    source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://repair-fail",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    source_id = source.payload.id if source.payload else ""
    upsert = svc.upsert_chunk(
        meta=_meta(),
        source_id=source_id,
        chunk_ordinal=1,
        reference_range="r",
        content_hash="h",
        text="text",
        metadata={},
    )
    assert upsert.ok
    active = svc.get_active_spec(meta=_meta()).payload
    assert active is not None

    with caplog.at_level(
        logging.WARNING, logger="services.state.embedding_authority.implementation"
    ):
        repaired = svc.repair_spec(meta=_meta(), spec_id=active.id, limit=5)

    assert not repaired.ok
    assert repaired.errors
    assert repaired.errors[0].category.value == "dependency"
    assert any("Repair operation failed" in item.message for item in caplog.records)


def test_invalid_ulid_is_validation_error_not_transport_error() -> None:
    """Malformed ULIDs should produce domain validation errors."""
    svc, _, _ = _service()
    result = svc.get_source(meta=_meta(), source_id="not-a-ulid")
    assert not result.ok
    assert result.errors
    assert result.errors[0].category.value == "validation"


def test_search_embeddings_returns_filtered_matches() -> None:
    """Search should return semantic matches and honor source-scoped filtering."""
    svc, _, _ = _service()
    first_source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://search-1",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    second_source = svc.upsert_source(
        meta=_meta(),
        canonical_reference="doc://search-2",
        source_type="note",
        service="ingestion",
        principal="operator",
        metadata={},
    )
    assert first_source.payload is not None
    assert second_source.payload is not None

    first_chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=first_source.payload.id,
        chunk_ordinal=1,
        reference_range="a",
        content_hash="h-a",
        text="alpha",
        metadata={},
    )
    second_chunk = svc.upsert_chunk(
        meta=_meta(),
        source_id=second_source.payload.id,
        chunk_ordinal=1,
        reference_range="b",
        content_hash="h-b",
        text="beta",
        metadata={},
    )
    assert first_chunk.payload is not None
    assert second_chunk.payload is not None

    result = svc.search_embeddings(
        meta=_meta(),
        query_text="any query",
        source_id=first_source.payload.id,
        spec_id="",
        limit=10,
    )
    assert result.ok
    assert result.payload is not None
    assert len(result.payload) == 1

    match: SearchEmbeddingMatch = result.payload[0]
    assert match.chunk_id == first_chunk.payload.chunk.id
    assert match.source_id == first_source.payload.id
