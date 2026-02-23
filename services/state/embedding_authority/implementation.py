"""Concrete Embedding Authority Service implementation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from pydantic import BaseModel, ValidationError
from packages.brain_shared.config import BrainSettings, EmbeddingServiceSettings
from packages.brain_shared.envelope import (
    EnvelopeMeta,
    Envelope,
    failure,
    success,
    validate_meta,
)
from packages.brain_shared.errors import (
    ErrorDetail,
    codes,
    dependency_error,
    not_found_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.substrates.postgres.errors import normalize_postgres_error
from services.state.embedding_authority.component import SERVICE_COMPONENT_ID
from services.state.embedding_authority.data import (
    EmbeddingPostgresRuntime,
    PostgresEmbeddingRepository,
)
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
from services.state.embedding_authority.interfaces import (
    EmbeddingRepository,
    QdrantIndexBackend,
)
from services.state.embedding_authority.qdrant_backend import QdrantEmbeddingBackend
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.embedding_authority.validation import (
    BatchChunkUpsertRequest,
    BatchEmbeddingVectorUpsertRequest,
    ChunkIdRequest,
    ChunkUpsertRequest,
    EmbeddingVectorUpsertRequest,
    GetEmbeddingRequest,
    ListEmbeddingsBySourceRequest,
    ListEmbeddingsByStatusRequest,
    SearchEmbeddingsRequest,
    SourceIdRequest,
    SourceUpsertRequest,
    SpecIdRequest,
    SpecUpsertRequest,
)

_CANON_RE = re.compile(r"[^\.a-z0-9_-]")
_LOGGER = get_logger(__name__)
_NO_PAYLOAD = object()


@dataclass
class _ActiveSpecState:
    """In-memory cache of persisted active-spec identity."""

    spec_id: str | None


class DefaultEmbeddingAuthorityService(EmbeddingAuthorityService):
    """Default EAS implementation with Postgres authority and Qdrant derived index."""

    def __init__(
        self,
        *,
        settings: EmbeddingServiceSettings,
        repository: EmbeddingRepository,
        index_backend: QdrantIndexBackend,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._index_backend = index_backend
        self._active_state = _ActiveSpecState(
            spec_id=self._repository.get_active_spec_id()
        )

    @classmethod
    def from_settings(
        cls, settings: BrainSettings
    ) -> "DefaultEmbeddingAuthorityService":
        """Build EAS from typed application settings and substrate runtimes."""
        embedding_settings = EmbeddingServiceSettings.model_validate(settings.embedding)
        runtime = EmbeddingPostgresRuntime.from_settings(settings)
        repository = PostgresEmbeddingRepository(runtime.schema_sessions)
        index_backend = QdrantEmbeddingBackend(
            qdrant_url=embedding_settings.qdrant_url,
            request_timeout_seconds=embedding_settings.request_timeout_seconds,
            distance_metric=embedding_settings.distance_metric,
        )
        return cls(
            settings=embedding_settings,
            repository=repository,
            index_backend=index_backend,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def upsert_spec(
        self,
        *,
        meta: EnvelopeMeta,
        provider: str,
        name: str,
        version: str,
        dimensions: int,
    ) -> Envelope[EmbeddingSpec]:
        """Create or return one embedding spec by canonical identity."""
        spec_request, errors = self._validate_request(
            meta=meta,
            model=SpecUpsertRequest,
            payload={
                "provider": provider,
                "name": name,
                "version": version,
                "dimensions": dimensions,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert spec_request is not None

        canonical = _canonical_spec_string(
            provider=spec_request.provider,
            name=spec_request.name,
            version=spec_request.version,
            dimensions=spec_request.dimensions,
        )
        hash_bytes = hashlib.sha256(canonical.encode("utf-8")).digest()

        try:
            spec = self._repository.upsert_spec(
                provider=spec_request.provider,
                name=spec_request.name,
                version=spec_request.version,
                dimensions=spec_request.dimensions,
                hash_bytes=hash_bytes,
                canonical_string=canonical,
            )
            self._index_backend.ensure_collection(
                spec_id=spec.id,
                dimensions=spec.dimensions,
            )
            return success(meta=meta, payload=spec)
        except Exception as exc:  # noqa: BLE001
            if self._is_postgres_error(exc):
                return self._postgres_failure(meta=meta, exc=exc)
            _LOGGER.warning(
                "Spec upsert failed due to dependency error: exception_type=%s",
                type(exc).__name__,
                exc_info=exc,
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "spec upsert failed",
                        code=codes.DEPENDENCY_FAILURE,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("spec_id",),
    )
    def set_active_spec(
        self, *, meta: EnvelopeMeta, spec_id: str
    ) -> Envelope[EmbeddingSpec]:
        """Persist and return active spec used for defaulted operations."""
        spec_request, errors = self._validate_request(
            meta=meta,
            model=SpecIdRequest,
            payload={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert spec_request is not None

        try:
            spec = self._repository.get_spec(spec_id=spec_request.spec_id)
            if spec is None:
                return self._not_found_failure(meta=meta, message="spec not found")
            self._index_backend.ensure_collection(
                spec_id=spec.id,
                dimensions=spec.dimensions,
            )
            self._repository.set_active_spec(spec_id=spec.id)
            self._active_state.spec_id = spec.id
            return success(meta=meta, payload=spec)
        except Exception as exc:  # noqa: BLE001
            if self._is_postgres_error(exc):
                return self._postgres_failure(meta=meta, exc=exc)
            _LOGGER.warning(
                "Set active spec failed due to dependency error: spec_id=%s exception_type=%s",
                spec_request.spec_id,
                type(exc).__name__,
                exc_info=exc,
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "set active spec failed",
                        code=codes.DEPENDENCY_FAILURE,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("principal",),
    )
    def upsert_source(
        self,
        *,
        meta: EnvelopeMeta,
        canonical_reference: str,
        source_type: str,
        service: str,
        principal: str,
        metadata: Mapping[str, str],
    ) -> Envelope[SourceRecord]:
        """Create/update source row."""
        source_request, errors = self._validate_request(
            meta=meta,
            model=SourceUpsertRequest,
            payload={
                "canonical_reference": canonical_reference,
                "source_type": source_type,
                "service": service,
                "principal": principal,
                "metadata": metadata,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert source_request is not None

        try:
            record = self._repository.upsert_source(
                canonical_reference=source_request.canonical_reference,
                source_type=source_request.source_type,
                service=source_request.service,
                principal=source_request.principal,
                metadata=source_request.metadata,
            )
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
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
    ) -> Envelope[ChunkRecord]:
        """Create/update chunk row."""
        chunk_request, errors = self._validate_request(
            meta=meta,
            model=ChunkUpsertRequest,
            payload={
                "source_id": source_id,
                "chunk_ordinal": chunk_ordinal,
                "reference_range": reference_range,
                "content_hash": content_hash,
                "text": text,
                "metadata": metadata,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert chunk_request is not None

        try:
            source = self._repository.get_source(source_id=chunk_request.source_id)
            if source is None:
                return self._not_found_failure(meta=meta, message="source not found")

            chunk = self._repository.upsert_chunk(
                source_id=source.id,
                chunk_ordinal=chunk_request.chunk_ordinal,
                reference_range=chunk_request.reference_range,
                content_hash=chunk_request.content_hash,
                text=chunk_request.text,
                metadata=chunk_request.metadata,
            )
            return success(meta=meta, payload=chunk)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def upsert_chunks(
        self,
        *,
        meta: EnvelopeMeta,
        items: Sequence[UpsertChunkInput],
    ) -> Envelope[list[ChunkRecord]]:
        """Batch upsert convenience API."""
        chunk_batch, errors = self._validate_request(
            meta=meta,
            model=BatchChunkUpsertRequest,
            payload={"items": items},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert chunk_batch is not None

        results: list[ChunkRecord] = []
        aggregate_errors: list[ErrorDetail] = []
        for item in chunk_batch.items:
            item_result = self.upsert_chunk(
                meta=meta,
                source_id=item.source_id,
                chunk_ordinal=item.chunk_ordinal,
                reference_range=item.reference_range,
                content_hash=item.content_hash,
                text=item.text,
                metadata=item.metadata,
            )
            if item_result.payload is not None:
                results.append(item_result.payload.value)
            if item_result.errors:
                aggregate_errors.extend(item_result.errors)

        if aggregate_errors:
            return failure(meta=meta, errors=aggregate_errors, payload=results)
        return success(meta=meta, payload=results)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("chunk_id", "spec_id"),
    )
    def upsert_embedding_vector(
        self,
        *,
        meta: EnvelopeMeta,
        chunk_id: str,
        spec_id: str,
        vector: Sequence[float],
    ) -> Envelope[EmbeddingRecord]:
        """Persist one vector point and indexed embedding status row."""
        vector_request, errors = self._validate_request(
            meta=meta,
            model=EmbeddingVectorUpsertRequest,
            payload={"chunk_id": chunk_id, "spec_id": spec_id, "vector": vector},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert vector_request is not None

        try:
            chunk = self._repository.get_chunk(chunk_id=vector_request.chunk_id)
            if chunk is None:
                return self._not_found_failure(meta=meta, message="chunk not found")

            spec_result = self._resolve_spec(meta=meta, spec_id=vector_request.spec_id)
            if spec_result.errors:
                return failure(meta=meta, errors=spec_result.errors)
            spec_payload = spec_result.payload
            spec = None if spec_payload is None else spec_payload.value
            if spec is None:
                return self._not_found_failure(meta=meta, message="spec not found")

            normalized_vector = tuple(float(value) for value in vector_request.vector)
            if len(normalized_vector) != spec.dimensions:
                return failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            f"vector dimension mismatch: expected {spec.dimensions}, got {len(normalized_vector)}",
                            code=codes.INVALID_ARGUMENT,
                        )
                    ],
                )

            try:
                self._index_backend.ensure_collection(
                    spec_id=spec.id,
                    dimensions=spec.dimensions,
                )
                self._index_backend.upsert_point(
                    spec_id=spec.id,
                    chunk_id=chunk.id,
                    vector=normalized_vector,
                    payload={
                        "chunk_id": chunk.id,
                        "source_id": chunk.source_id,
                        "spec_id": spec.id,
                        "chunk_ordinal": chunk.chunk_ordinal,
                        "reference_range": chunk.reference_range,
                        "content_hash": chunk.content_hash,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Vector upsert failed; row marked FAILED: spec_id=%s chunk_id=%s source_id=%s exception_type=%s",
                    spec.id,
                    chunk.id,
                    chunk.source_id,
                    type(exc).__name__,
                    exc_info=exc,
                )
                self._repository.upsert_embedding(
                    chunk_id=chunk.id,
                    spec_id=spec.id,
                    content_hash=chunk.content_hash,
                    status=EmbeddingStatus.FAILED,
                    error_detail=f"{type(exc).__name__}: {exc}",
                )
                return failure(
                    meta=meta,
                    errors=[
                        dependency_error(
                            "vector upsert failed",
                            code=codes.DEPENDENCY_FAILURE,
                            metadata={"exception_type": type(exc).__name__},
                        )
                    ],
                )

            record = self._repository.upsert_embedding(
                chunk_id=chunk.id,
                spec_id=spec.id,
                content_hash=chunk.content_hash,
                status=EmbeddingStatus.INDEXED,
                error_detail="",
            )
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def upsert_embedding_vectors(
        self,
        *,
        meta: EnvelopeMeta,
        items: Sequence[UpsertEmbeddingVectorInput],
    ) -> Envelope[list[EmbeddingRecord]]:
        """Batch upsert convenience API for vector writes."""
        vector_batch, errors = self._validate_request(
            meta=meta,
            model=BatchEmbeddingVectorUpsertRequest,
            payload={"items": items},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert vector_batch is not None

        results: list[EmbeddingRecord] = []
        aggregate_errors: list[ErrorDetail] = []
        for item in vector_batch.items:
            item_result = self.upsert_embedding_vector(
                meta=meta,
                chunk_id=item.chunk_id,
                spec_id=item.spec_id,
                vector=item.vector,
            )
            if item_result.payload is not None:
                results.append(item_result.payload.value)
            if item_result.errors:
                aggregate_errors.extend(item_result.errors)

        if aggregate_errors:
            return failure(meta=meta, errors=aggregate_errors, payload=results)
        return success(meta=meta, payload=results)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("chunk_id",),
    )
    def delete_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Envelope[bool]:
        """Hard-delete one chunk and best-effort delete derived index points."""
        chunk_request, errors = self._validate_request(
            meta=meta,
            model=ChunkIdRequest,
            payload={"chunk_id": chunk_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=False)
        assert chunk_request is not None

        try:
            deleted = self._repository.delete_chunk(chunk_id=chunk_request.chunk_id)
            if not deleted:
                return self._not_found_failure(
                    meta=meta,
                    message="chunk not found",
                    payload=False,
                )

            for spec_id in self._repository.list_spec_ids():
                self._delete_derived_point_best_effort(
                    spec_id=spec_id, chunk_id=chunk_request.chunk_id
                )
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=False)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
    def delete_source(self, *, meta: EnvelopeMeta, source_id: str) -> Envelope[bool]:
        """Hard-delete one source and all owned chunk/embedding rows."""
        source_request, errors = self._validate_request(
            meta=meta,
            model=SourceIdRequest,
            payload={"source_id": source_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=False)
        assert source_request is not None

        try:
            chunk_ids = self._repository.list_chunk_ids_for_source(
                source_id=source_request.source_id
            )
            deleted = self._repository.delete_source(source_id=source_request.source_id)
            if not deleted:
                return self._not_found_failure(
                    meta=meta,
                    message="source not found",
                    payload=False,
                )

            spec_ids = self._repository.list_spec_ids()
            for chunk_row_id in chunk_ids:
                for spec_id in spec_ids:
                    self._delete_derived_point_best_effort(
                        spec_id=spec_id, chunk_id=chunk_row_id
                    )
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=False)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
    def get_source(
        self, *, meta: EnvelopeMeta, source_id: str
    ) -> Envelope[SourceRecord]:
        """Read one source by id."""
        source_request, errors = self._validate_request(
            meta=meta,
            model=SourceIdRequest,
            payload={"source_id": source_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert source_request is not None

        try:
            record = self._repository.get_source(source_id=source_request.source_id)
            if record is None:
                return self._not_found_failure(meta=meta, message="source not found")
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("principal",),
    )
    def list_sources(
        self,
        *,
        meta: EnvelopeMeta,
        canonical_reference: str,
        service: str,
        principal: str,
        limit: int,
    ) -> Envelope[list[SourceRecord]]:
        """List sources by optional filters."""
        errors = self._validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        try:
            records = self._repository.list_sources(
                canonical_reference=canonical_reference,
                service=service,
                principal=principal,
                limit=self._clamp_limit(limit),
            )
            return success(meta=meta, payload=records)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta, errors=[normalize_postgres_error(exc)], payload=[]
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("chunk_id",),
    )
    def get_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Envelope[ChunkRecord]:
        """Read one chunk by id."""
        chunk_request, errors = self._validate_request(
            meta=meta,
            model=ChunkIdRequest,
            payload={"chunk_id": chunk_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert chunk_request is not None

        try:
            record = self._repository.get_chunk(chunk_id=chunk_request.chunk_id)
            if record is None:
                return self._not_found_failure(meta=meta, message="chunk not found")
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
    def list_chunks_by_source(
        self,
        *,
        meta: EnvelopeMeta,
        source_id: str,
        limit: int,
    ) -> Envelope[list[ChunkRecord]]:
        """List chunk rows for one source."""
        source_request, errors = self._validate_request(
            meta=meta,
            model=SourceIdRequest,
            payload={"source_id": source_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert source_request is not None

        try:
            records = self._repository.list_chunks_by_source(
                source_id=source_request.source_id,
                limit=self._clamp_limit(limit),
            )
            return success(meta=meta, payload=records)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=[])

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("chunk_id", "spec_id"),
    )
    def get_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        chunk_id: str,
        spec_id: str = "",
    ) -> Envelope[EmbeddingRecord]:
        """Read one embedding row."""
        embedding_request, errors = self._validate_request(
            meta=meta,
            model=GetEmbeddingRequest,
            payload={"chunk_id": chunk_id, "spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert embedding_request is not None

        spec_result = self._resolve_spec(meta=meta, spec_id=embedding_request.spec_id)
        if spec_result.errors:
            return failure(meta=meta, errors=spec_result.errors)
        spec_payload = spec_result.payload
        spec = None if spec_payload is None else spec_payload.value
        if spec is None:
            return self._not_found_failure(meta=meta, message="spec not found")

        try:
            record = self._repository.get_embedding(
                chunk_id=embedding_request.chunk_id, spec_id=spec.id
            )
            if record is None:
                return self._not_found_failure(meta=meta, message="embedding not found")
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id", "spec_id"),
    )
    def list_embeddings_by_source(
        self,
        *,
        meta: EnvelopeMeta,
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> Envelope[list[EmbeddingRecord]]:
        """List embedding rows for one source."""
        list_request, errors = self._validate_request(
            meta=meta,
            model=ListEmbeddingsBySourceRequest,
            payload={"source_id": source_id, "spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert list_request is not None

        try:
            records = self._repository.list_embeddings_by_source(
                source_id=list_request.source_id,
                spec_id=list_request.spec_id,
                limit=self._clamp_limit(limit),
            )
            return success(meta=meta, payload=records)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=[])

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("spec_id",),
    )
    def list_embeddings_by_status(
        self,
        *,
        meta: EnvelopeMeta,
        status: EmbeddingStatus,
        spec_id: str,
        limit: int,
    ) -> Envelope[list[EmbeddingRecord]]:
        """List embedding rows by status."""
        status_request, errors = self._validate_request(
            meta=meta,
            model=ListEmbeddingsByStatusRequest,
            payload={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert status_request is not None

        try:
            records = self._repository.list_embeddings_by_status(
                status=status,
                spec_id=status_request.spec_id,
                limit=self._clamp_limit(limit),
            )
            return success(meta=meta, payload=records)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=[])

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id", "spec_id"),
    )
    def search_embeddings(
        self,
        *,
        meta: EnvelopeMeta,
        query_vector: Sequence[float],
        source_id: str,
        spec_id: str,
        limit: int,
    ) -> Envelope[list[SearchEmbeddingMatch]]:
        """Search derived embeddings by semantic similarity."""
        search_request, errors = self._validate_request(
            meta=meta,
            model=SearchEmbeddingsRequest,
            payload={
                "query_vector": query_vector,
                "source_id": source_id,
                "spec_id": spec_id,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])
        assert search_request is not None

        spec_result = self._resolve_spec(meta=meta, spec_id=search_request.spec_id)
        if spec_result.errors:
            return failure(meta=meta, errors=spec_result.errors, payload=[])
        spec_payload = spec_result.payload
        spec = None if spec_payload is None else spec_payload.value
        if spec is None:
            return self._not_found_failure(
                meta=meta, message="spec not found", payload=[]
            )

        vector = tuple(float(value) for value in search_request.query_vector)
        if len(vector) != spec.dimensions:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"query_vector dimension mismatch: expected {spec.dimensions}, got {len(vector)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
                payload=[],
            )

        try:
            hits = self._index_backend.search_points(
                spec_id=spec.id,
                source_id=search_request.source_id,
                query_vector=vector,
                limit=self._clamp_limit(limit),
            )

            matches: list[SearchEmbeddingMatch] = []
            for hit in hits:
                chunk_id = str(hit.payload.get("chunk_id", "")).strip()
                if not chunk_id:
                    continue
                chunk_ordinal_raw = hit.payload.get("chunk_ordinal", 0)
                try:
                    chunk_ordinal = int(chunk_ordinal_raw)
                except (TypeError, ValueError):
                    chunk_ordinal = 0
                matches.append(
                    SearchEmbeddingMatch(
                        score=float(hit.score),
                        chunk_id=chunk_id,
                        source_id=str(hit.payload.get("source_id", "")),
                        spec_id=str(hit.payload.get("spec_id", spec.id)),
                        chunk_ordinal=chunk_ordinal,
                        reference_range=str(hit.payload.get("reference_range", "")),
                        content_hash=str(hit.payload.get("content_hash", "")),
                    )
                )
            return success(meta=meta, payload=matches)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Search operation failed: spec_id=%s source_id=%s exception_type=%s",
                spec.id,
                search_request.source_id,
                type(exc).__name__,
                exc_info=exc,
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "search failed",
                        code=codes.DEPENDENCY_FAILURE,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
                payload=[],
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_active_spec(self, *, meta: EnvelopeMeta) -> Envelope[EmbeddingSpec]:
        """Return persisted active spec."""
        errors = self._validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors)

        spec_result = self._resolve_spec(meta=meta, spec_id="")
        if spec_result.errors:
            return failure(meta=meta, errors=spec_result.errors)
        spec_payload = spec_result.payload
        spec = None if spec_payload is None else spec_payload.value
        if spec is None:
            return self._not_found_failure(meta=meta, message="active spec not set")
        return success(meta=meta, payload=spec)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def list_specs(
        self, *, meta: EnvelopeMeta, limit: int
    ) -> Envelope[list[EmbeddingSpec]]:
        """List known embedding specs."""
        errors = self._validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        try:
            rows = self._repository.list_specs(limit=self._clamp_limit(limit))
            return success(meta=meta, payload=rows)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta, errors=[normalize_postgres_error(exc)], payload=[]
            )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("spec_id",),
    )
    def get_spec(self, *, meta: EnvelopeMeta, spec_id: str) -> Envelope[EmbeddingSpec]:
        """Read one embedding spec by id."""
        spec_request, errors = self._validate_request(
            meta=meta,
            model=SpecIdRequest,
            payload={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert spec_request is not None

        try:
            row = self._repository.get_spec(spec_id=spec_request.spec_id)
            if row is None:
                return self._not_found_failure(meta=meta, message="spec not found")
            return success(meta=meta, payload=row)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    def _resolve_spec(
        self, *, meta: EnvelopeMeta, spec_id: str
    ) -> Envelope[EmbeddingSpec]:
        """Resolve explicit spec id or persisted active spec id to a full spec row."""
        try:
            effective_id = (
                spec_id
                if spec_id
                else (
                    self._active_state.spec_id or self._repository.get_active_spec_id()
                )
            )
            if not effective_id:
                return failure(
                    meta=meta,
                    errors=[
                        not_found_error(
                            "active spec not set",
                            code=codes.RESOURCE_NOT_FOUND,
                        )
                    ],
                )
            row = self._repository.get_spec(spec_id=effective_id)
            if row is None:
                return failure(
                    meta=meta,
                    errors=[
                        not_found_error("spec not found", code=codes.RESOURCE_NOT_FOUND)
                    ],
                )
            return success(meta=meta, payload=row)
        except Exception as exc:  # noqa: BLE001
            return failure(meta=meta, errors=[normalize_postgres_error(exc)])

    def _validate_meta(self, meta: EnvelopeMeta) -> list[ErrorDetail]:
        """Validate envelope metadata and convert failures to typed errors."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return [validation_error(str(exc), code=codes.MISSING_REQUIRED_FIELD)]
        return []

    def _clamp_limit(self, limit: int) -> int:
        """Clamp list limits to configured max."""
        if limit <= 0:
            return min(100, self._settings.max_list_limit)
        return min(limit, self._settings.max_list_limit)

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: Mapping[str, object],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and one request payload model."""
        errors = self._validate_meta(meta)
        if errors:
            return None, errors
        try:
            return model.model_validate(payload), []
        except ValidationError as exc:
            return None, self._validation_errors(exc)

    def _validation_errors(self, exc: ValidationError) -> list[ErrorDetail]:
        """Normalize Pydantic validation failures to typed domain errors."""
        normalized: list[ErrorDetail] = []
        for item in exc.errors():
            message = str(item.get("msg", "invalid request"))
            normalized.append(
                validation_error(
                    message,
                    code=self._validation_code_for_message(message),
                )
            )
        return normalized

    def _validation_code_for_message(self, message: str) -> str:
        """Map one validation message to a stable public error code."""
        if message.endswith("is required"):
            return codes.MISSING_REQUIRED_FIELD
        if message.endswith("must not be empty"):
            return codes.MISSING_REQUIRED_FIELD
        return codes.INVALID_ARGUMENT

    def _not_found_failure(
        self,
        *,
        meta: EnvelopeMeta,
        message: str,
        payload: object = _NO_PAYLOAD,
    ) -> Envelope[object]:
        """Return standardized not-found failure envelope."""
        errors = [not_found_error(message, code=codes.RESOURCE_NOT_FOUND)]
        if payload is _NO_PAYLOAD:
            return failure(meta=meta, errors=errors)
        return failure(meta=meta, errors=errors, payload=payload)

    def _postgres_failure(
        self,
        *,
        meta: EnvelopeMeta,
        exc: Exception,
        payload: object = _NO_PAYLOAD,
    ) -> Envelope[object]:
        """Return standardized Postgres-normalized failure envelope."""
        errors = [normalize_postgres_error(exc)]
        if payload is _NO_PAYLOAD:
            return failure(meta=meta, errors=errors)
        return failure(meta=meta, errors=errors, payload=payload)

    def _delete_derived_point_best_effort(self, *, spec_id: str, chunk_id: str) -> None:
        """Best-effort derived index cleanup with explicit observability."""
        try:
            self._index_backend.delete_point(spec_id=spec_id, chunk_id=chunk_id)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Best-effort derived cleanup failed: spec_id=%s chunk_id=%s exception_type=%s",
                spec_id,
                chunk_id,
                type(exc).__name__,
                exc_info=exc,
            )

    def _is_postgres_error(self, exc: Exception) -> bool:
        """Best-effort classifier for SQL-related exceptions."""
        module_name = type(exc).__module__
        return "sqlalchemy" in module_name or "psycopg" in module_name


def _canonical_spec_string(
    *, provider: str, name: str, version: str, dimensions: int
) -> str:
    """Build canonical spec serialization used for hash identity."""
    parts = (provider, name, version, str(dimensions))
    normalized = []
    for part in parts:
        lowered = part.strip().lower()
        normalized.append(_CANON_RE.sub("", lowered))
    return ":".join(normalized)
