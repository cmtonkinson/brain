"""Concrete Embedding Authority Service implementation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

from packages.brain_shared.envelope import (
    EnvelopeMeta,
    Result,
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
from packages.brain_shared.ids import ulid_str_to_bytes
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
    RepairSpecResult,
    SourceRecord,
    UpsertChunkInput,
    UpsertChunkResult,
)
from services.state.embedding_authority.interfaces import (
    EmbeddingRepository,
    EmbeddingVectorizer,
    QdrantIndexBackend,
)
from services.state.embedding_authority.qdrant_backend import QdrantEmbeddingBackend
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.embedding_authority.settings import EmbeddingSettings

_CANON_RE = re.compile(r"[^\.a-z0-9_-]")
_LOGGER = get_logger(__name__)
_NO_PAYLOAD = object()


@dataclass(frozen=True)
class _ActiveSpec:
    """Cached active-spec state used for new writes."""

    spec: EmbeddingSpec


class DeterministicHashVectorizer(EmbeddingVectorizer):
    """Deterministic fallback vectorizer for current EAS implementation.

    This is intentionally simple so EAS lifecycle behavior is testable without
    embedding-provider dependencies.
    """

    def embed(self, *, text: str, dimensions: int) -> tuple[float, ...]:
        """Map text deterministically to a fixed-length float vector."""
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        counter = 0
        while len(values) < dimensions:
            block = hashlib.sha256(seed + counter.to_bytes(8, "big")).digest()
            for idx in range(0, len(block), 4):
                chunk = block[idx : idx + 4]
                if len(chunk) < 4:
                    break
                values.append(int.from_bytes(chunk, "big") / 4_294_967_295.0)
                if len(values) >= dimensions:
                    break
            counter += 1
        return tuple(values)


class DefaultEmbeddingAuthorityService(EmbeddingAuthorityService):
    """Default EAS implementation with Postgres authority and Qdrant derived index."""

    def __init__(
        self,
        *,
        settings: EmbeddingSettings,
        repository: EmbeddingRepository,
        index_backend: QdrantIndexBackend,
        vectorizer: EmbeddingVectorizer,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._index_backend = index_backend
        self._vectorizer = vectorizer
        self._active = _ActiveSpec(spec=self._bootstrap_active_spec())

    @classmethod
    def from_config(
        cls, config: Mapping[str, object]
    ) -> "DefaultEmbeddingAuthorityService":
        """Build EAS from merged config and shared substrate runtimes."""
        settings = EmbeddingSettings.from_config(config)
        runtime = EmbeddingPostgresRuntime.from_config(config)
        repository = PostgresEmbeddingRepository(runtime.schema_sessions)
        index_backend = QdrantEmbeddingBackend(
            qdrant_url=settings.qdrant_url,
            request_timeout_seconds=settings.request_timeout_seconds,
            distance_metric=settings.distance_metric,
        )
        vectorizer = DeterministicHashVectorizer()
        return cls(
            settings=settings,
            repository=repository,
            index_backend=index_backend,
            vectorizer=vectorizer,
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
    ) -> Result[SourceRecord]:
        """Create/update source row."""
        errors = self._collect_errors(
            meta=meta,
            required_fields={
                "canonical_reference": canonical_reference,
                "source_type": source_type,
                "service": service,
                "principal": principal,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            record = self._repository.upsert_source(
                canonical_reference=canonical_reference,
                source_type=source_type,
                service=service,
                principal=principal,
                metadata=metadata,
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
    ) -> Result[UpsertChunkResult]:
        """Create/update chunk row and materialize active-spec embedding."""
        errors = self._collect_errors(
            meta=meta,
            required_ulids={"source_id": source_id},
            required_fields={
                "content_hash": content_hash,
                "text": text,
            },
        )
        if chunk_ordinal < 0:
            errors.append(
                validation_error(
                    "chunk_ordinal must be >= 0", code=codes.INVALID_ARGUMENT
                )
            )
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            source = self._repository.get_source(source_id=source_id)
            if source is None:
                return self._not_found_failure(meta=meta, message="source not found")

            chunk = self._repository.upsert_chunk(
                source_id=source.id,
                chunk_ordinal=chunk_ordinal,
                reference_range=reference_range,
                content_hash=content_hash,
                text=text,
                metadata=metadata,
            )
            embedding = self._materialize_embedding(chunk=chunk)
            return success(
                meta=meta, payload=UpsertChunkResult(chunk=chunk, embedding=embedding)
            )
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
    ) -> Result[list[UpsertChunkResult]]:
        """Batch upsert convenience API."""
        errors = self._validate_meta(meta)
        if not items:
            errors.append(
                validation_error(
                    "items must not be empty", code=codes.MISSING_REQUIRED_FIELD
                )
            )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        results: list[UpsertChunkResult] = []
        aggregate_errors: list[ErrorDetail] = []
        for item in items:
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
                results.append(item_result.payload)
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
    def delete_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Result[bool]:
        """Hard-delete one chunk and best-effort delete derived index points."""
        errors = self._collect_errors(meta=meta, required_ulids={"chunk_id": chunk_id})
        if errors:
            return failure(meta=meta, errors=errors, payload=False)

        try:
            deleted = self._repository.delete_chunk(chunk_id=chunk_id)
            if not deleted:
                return self._not_found_failure(
                    meta=meta,
                    message="chunk not found",
                    payload=False,
                )

            for spec_id in self._repository.list_spec_ids():
                self._delete_derived_point_best_effort(
                    spec_id=spec_id, chunk_id=chunk_id
                )
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=False)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
    def delete_source(self, *, meta: EnvelopeMeta, source_id: str) -> Result[bool]:
        """Hard-delete one source and all owned chunk/embedding rows."""
        errors = self._collect_errors(
            meta=meta, required_ulids={"source_id": source_id}
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=False)

        try:
            chunk_ids = self._repository.list_chunk_ids_for_source(source_id=source_id)
            deleted = self._repository.delete_source(source_id=source_id)
            if not deleted:
                return self._not_found_failure(
                    meta=meta,
                    message="source not found",
                    payload=False,
                )

            spec_ids = self._repository.list_spec_ids()
            for chunk_id in chunk_ids:
                for spec_id in spec_ids:
                    self._delete_derived_point_best_effort(
                        spec_id=spec_id, chunk_id=chunk_id
                    )
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=False)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("source_id",),
    )
    def get_source(self, *, meta: EnvelopeMeta, source_id: str) -> Result[SourceRecord]:
        """Read one source by id."""
        errors = self._collect_errors(
            meta=meta, required_ulids={"source_id": source_id}
        )
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            record = self._repository.get_source(source_id=source_id)
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
    ) -> Result[list[SourceRecord]]:
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
    def get_chunk(self, *, meta: EnvelopeMeta, chunk_id: str) -> Result[ChunkRecord]:
        """Read one chunk by id."""
        errors = self._collect_errors(meta=meta, required_ulids={"chunk_id": chunk_id})
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            record = self._repository.get_chunk(chunk_id=chunk_id)
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
    ) -> Result[list[ChunkRecord]]:
        """List chunk rows for one source."""
        errors = self._collect_errors(
            meta=meta, required_ulids={"source_id": source_id}
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        try:
            records = self._repository.list_chunks_by_source(
                source_id=source_id,
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
    ) -> Result[EmbeddingRecord]:
        """Read one embedding row."""
        errors = self._collect_errors(
            meta=meta,
            required_ulids={"chunk_id": chunk_id},
            optional_ulids={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors)

        effective_spec_id = spec_id or self._active.spec.id
        try:
            record = self._repository.get_embedding(
                chunk_id=chunk_id, spec_id=effective_spec_id
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
    ) -> Result[list[EmbeddingRecord]]:
        """List embedding rows for one source."""
        errors = self._collect_errors(
            meta=meta,
            required_ulids={"source_id": source_id},
            optional_ulids={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        effective_spec_id = spec_id or self._active.spec.id
        try:
            records = self._repository.list_embeddings_by_source(
                source_id=source_id,
                spec_id=effective_spec_id,
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
    ) -> Result[list[EmbeddingRecord]]:
        """List embedding rows by status."""
        errors = self._collect_errors(
            meta=meta,
            optional_ulids={"spec_id": spec_id},
        )
        if errors:
            return failure(meta=meta, errors=errors, payload=[])

        effective_spec_id = spec_id or self._active.spec.id
        try:
            records = self._repository.list_embeddings_by_status(
                status=status,
                spec_id=effective_spec_id,
                limit=self._clamp_limit(limit),
            )
            return success(meta=meta, payload=records)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc, payload=[])

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def get_active_spec(self, *, meta: EnvelopeMeta) -> Result[EmbeddingSpec]:
        """Return in-memory active spec."""
        errors = self._validate_meta(meta)
        if errors:
            return failure(meta=meta, errors=errors)
        return success(meta=meta, payload=self._active.spec)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def list_specs(
        self, *, meta: EnvelopeMeta, limit: int
    ) -> Result[list[EmbeddingSpec]]:
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
    def get_spec(self, *, meta: EnvelopeMeta, spec_id: str) -> Result[EmbeddingSpec]:
        """Read one embedding spec by id."""
        errors = self._collect_errors(meta=meta, required_ulids={"spec_id": spec_id})
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            row = self._repository.get_spec(spec_id=spec_id)
            if row is None:
                return self._not_found_failure(meta=meta, message="spec not found")
            return success(meta=meta, payload=row)
        except Exception as exc:  # noqa: BLE001
            return self._postgres_failure(meta=meta, exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("spec_id",),
    )
    def repair_spec(
        self,
        *,
        meta: EnvelopeMeta,
        spec_id: str,
        limit: int,
    ) -> Result[RepairSpecResult]:
        """Repair missing/stale derived Qdrant points for one spec."""
        errors = self._collect_errors(
            meta=meta,
            optional_ulids={"spec_id": spec_id},
        )
        effective_spec_id = spec_id or self._active.spec.id
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            spec = self._repository.get_spec(spec_id=effective_spec_id)
            if spec is None:
                return self._not_found_failure(meta=meta, message="spec not found")

            indexed = self._repository.list_embeddings_by_status(
                status=EmbeddingStatus.INDEXED,
                spec_id=spec.id,
                limit=min(self._clamp_limit(limit), self._settings.repair_batch_limit),
            )

            repaired = 0
            reembedded = 0
            for item in indexed:
                chunk = self._repository.get_chunk(chunk_id=item.chunk_id)
                if chunk is None:
                    continue

                should_reembed = chunk.content_hash != item.content_hash
                point_exists = self._index_backend.point_exists(
                    spec_id=spec.id,
                    chunk_id=chunk.id,
                )

                if should_reembed or not point_exists:
                    vector = self._vectorizer.embed(
                        text=chunk.text, dimensions=spec.dimensions
                    )
                    self._index_backend.upsert_point(
                        spec_id=spec.id,
                        chunk_id=chunk.id,
                        vector=vector,
                        payload={
                            "source_id": chunk.source_id,
                            "spec_id": spec.id,
                            "chunk_ordinal": chunk.chunk_ordinal,
                            "reference_range": chunk.reference_range,
                            "content_hash": chunk.content_hash,
                        },
                    )
                    self._repository.upsert_embedding(
                        chunk_id=chunk.id,
                        spec_id=spec.id,
                        content_hash=chunk.content_hash,
                        status=EmbeddingStatus.INDEXED,
                        error_detail="",
                    )
                    repaired += 1
                    if should_reembed:
                        reembedded += 1

            result = RepairSpecResult(
                spec_id=spec.id,
                scanned=len(indexed),
                repaired=repaired,
                reembedded=reembedded,
            )
            _LOGGER.info(
                "Repair completed: spec_id=%s scanned=%s repaired=%s reembedded=%s",
                result.spec_id,
                result.scanned,
                result.repaired,
                result.reembedded,
            )
            return success(
                meta=meta,
                payload=result,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Repair operation failed: spec_id=%s exception_type=%s",
                effective_spec_id,
                type(exc).__name__,
                exc_info=exc,
            )
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "repair failed",
                        code=codes.DEPENDENCY_FAILURE,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
            )

    def _bootstrap_active_spec(self) -> EmbeddingSpec:
        """Ensure active spec exists in Postgres and Qdrant on startup."""
        canonical = _canonical_spec_string(
            provider=self._settings.provider,
            name=self._settings.name,
            version=self._settings.version,
            dimensions=self._settings.dimensions,
        )
        hash_bytes = hashlib.sha256(canonical.encode("utf-8")).digest()

        spec = self._repository.ensure_spec(
            provider=self._settings.provider,
            name=self._settings.name,
            version=self._settings.version,
            dimensions=self._settings.dimensions,
            hash_bytes=hash_bytes,
            canonical_string=canonical,
        )
        self._index_backend.ensure_collection(
            spec_id=spec.id, dimensions=spec.dimensions
        )
        _LOGGER.info(
            "Active embedding spec ensured: spec_id=%s provider=%s name=%s version=%s dimensions=%s",
            spec.id,
            spec.provider,
            spec.name,
            spec.version,
            spec.dimensions,
        )
        return spec

    def _materialize_embedding(self, *, chunk: ChunkRecord) -> EmbeddingRecord:
        """Upsert active-spec embedding row and derived Qdrant point for one chunk."""
        spec = self._active.spec
        existing = self._repository.get_embedding(chunk_id=chunk.id, spec_id=spec.id)
        if (
            existing is not None
            and existing.content_hash == chunk.content_hash
            and existing.status == EmbeddingStatus.INDEXED
        ):
            return existing

        try:
            vector = self._vectorizer.embed(text=chunk.text, dimensions=spec.dimensions)
            self._index_backend.upsert_point(
                spec_id=spec.id,
                chunk_id=chunk.id,
                vector=vector,
                payload={
                    "source_id": chunk.source_id,
                    "spec_id": spec.id,
                    "chunk_ordinal": chunk.chunk_ordinal,
                    "reference_range": chunk.reference_range,
                    "content_hash": chunk.content_hash,
                },
            )
            return self._repository.upsert_embedding(
                chunk_id=chunk.id,
                spec_id=spec.id,
                content_hash=chunk.content_hash,
                status=EmbeddingStatus.INDEXED,
                error_detail="",
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Embedding materialization failed; row marked FAILED: spec_id=%s chunk_id=%s source_id=%s exception_type=%s",
                spec.id,
                chunk.id,
                chunk.source_id,
                type(exc).__name__,
                exc_info=exc,
            )
            return self._repository.upsert_embedding(
                chunk_id=chunk.id,
                spec_id=spec.id,
                content_hash=chunk.content_hash,
                status=EmbeddingStatus.FAILED,
                error_detail=f"{type(exc).__name__}: {exc}",
            )

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

    def _validate_ulid(self, *, value: str, field_name: str) -> ErrorDetail | None:
        """Validate ULID string fields and return a typed validation error."""
        try:
            ulid_str_to_bytes(value)
        except ValueError:
            return validation_error(
                f"{field_name} must be a valid ULID string",
                code=codes.INVALID_ARGUMENT,
            )
        return None

    def _collect_errors(
        self,
        *,
        meta: EnvelopeMeta,
        required_fields: Mapping[str, str] | None = None,
        required_ulids: Mapping[str, str] | None = None,
        optional_ulids: Mapping[str, str] | None = None,
    ) -> list[ErrorDetail]:
        """Collect and return validation errors for common request shapes."""
        errors = self._validate_meta(meta)
        if required_fields:
            for field_name, value in required_fields.items():
                if not value:
                    errors.append(
                        validation_error(
                            f"{field_name} is required",
                            code=codes.MISSING_REQUIRED_FIELD,
                        )
                    )
        if required_ulids:
            for field_name, value in required_ulids.items():
                if not value:
                    errors.append(
                        validation_error(
                            f"{field_name} is required",
                            code=codes.MISSING_REQUIRED_FIELD,
                        )
                    )
                    continue
                ulid_error = self._validate_ulid(value=value, field_name=field_name)
                if ulid_error is not None:
                    errors.append(ulid_error)
        if optional_ulids:
            for field_name, value in optional_ulids.items():
                if not value:
                    continue
                ulid_error = self._validate_ulid(value=value, field_name=field_name)
                if ulid_error is not None:
                    errors.append(ulid_error)
        return errors

    def _not_found_failure(
        self,
        *,
        meta: EnvelopeMeta,
        message: str,
        payload: object = _NO_PAYLOAD,
    ) -> Result[object]:
        """Return standardized not-found failure result."""
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
    ) -> Result[object]:
        """Return standardized Postgres-normalized failure result."""
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
