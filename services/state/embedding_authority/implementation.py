"""Concrete Embedding Authority Service implementation."""

from __future__ import annotations

from typing import Mapping, Sequence

from packages.brain_shared.envelope import EnvelopeKind, EnvelopeMeta, Result, failure, success
from packages.brain_shared.errors import ErrorDetail, codes, dependency_error, not_found_error, validation_error
from services.state.embedding_authority.data import (
    EmbeddingAuditRepository,
    EmbeddingDataUnitOfWork,
    EmbeddingPostgresRuntime,
)
from services.state.embedding_authority.domain import EmbeddingMatch, EmbeddingRecord, EmbeddingRef
from services.state.embedding_authority.interfaces import EmbeddingBackend
from services.state.embedding_authority.qdrant_backend import QdrantEmbeddingBackend
from services.state.embedding_authority.service import EmbeddingAuthorityService
from services.state.embedding_authority.settings import EmbeddingSettings


class DefaultEmbeddingAuthorityService(EmbeddingAuthorityService):
    """Default EAS implementation backed by Qdrant with EAS-owned DB wiring."""

    def __init__(
        self,
        settings: EmbeddingSettings,
        backend: EmbeddingBackend,
        *,
        db_runtime: EmbeddingPostgresRuntime | None = None,
        audit_repository: EmbeddingAuditRepository | None = None,
        data_uow: EmbeddingDataUnitOfWork | None = None,
    ) -> None:
        self._settings = settings
        self._backend = backend
        self._db_runtime = db_runtime
        self._audit_repository = audit_repository
        self._data_uow = data_uow

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "DefaultEmbeddingAuthorityService":
        """Construct service and backend from merged application config mapping."""
        settings = EmbeddingSettings.from_config(config)
        backend = QdrantEmbeddingBackend(settings=settings)
        db_runtime = EmbeddingPostgresRuntime.from_config(config)
        audit_repository = EmbeddingAuditRepository(db_runtime.schema_sessions)
        data_uow = EmbeddingDataUnitOfWork(db_runtime.schema_sessions)
        return cls(
            settings=settings,
            backend=backend,
            db_runtime=db_runtime,
            audit_repository=audit_repository,
            data_uow=data_uow,
        )

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
        errors = self._validate_meta(meta=meta)
        errors.extend(self._validate_ref_and_model(ref=ref, model=model))
        if errors:
            return failure(meta=meta, errors=errors)

        if len(vector) == 0:
            return failure(
                meta=meta,
                errors=[validation_error("vector must not be empty", code=codes.INVALID_ARGUMENT)],
            )

        model_dimension = self._settings.model_dimensions.get(model)
        if model_dimension is not None and model_dimension != len(vector):
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"vector dimension mismatch for model '{model}': expected {model_dimension}, got {len(vector)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        try:
            collection_size = self._backend.get_collection_vector_size()
            if collection_size is not None and collection_size != len(vector):
                return failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            f"vector dimension mismatch for collection '{self._settings.collection_name}': expected {collection_size}, got {len(vector)}",
                            code=codes.INVALID_ARGUMENT,
                        )
                    ],
                )

            stored = self._backend.upsert(
                ref=ref,
                vector=vector,
                model=model,
                metadata={str(key): str(value) for key, value in metadata.items()},
            )
            return success(meta=meta, payload=stored)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "embedding backend unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        retryable=True,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
            )

    def get_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
    ) -> Result[EmbeddingRecord]:
        """Read one embedding record."""
        errors = self._validate_meta(meta=meta)
        errors.extend(self._validate_ref(ref=ref))
        if errors:
            return failure(meta=meta, errors=errors)

        try:
            record = self._backend.get(ref=ref)
            if record is None:
                return failure(
                    meta=meta,
                    errors=[
                        not_found_error(
                            f"embedding not found for namespace='{ref.namespace}' key='{ref.key}'",
                            code=codes.RESOURCE_NOT_FOUND,
                        )
                    ],
                    payload=None,
                )
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "embedding backend unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        retryable=True,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
                payload=None,
            )

    def delete_embedding(
        self,
        *,
        meta: EnvelopeMeta,
        ref: EmbeddingRef,
        missing_ok: bool,
    ) -> Result[bool]:
        """Delete one embedding record."""
        errors = self._validate_meta(meta=meta)
        errors.extend(self._validate_ref(ref=ref))
        if errors:
            return failure(meta=meta, errors=errors, payload=False)

        try:
            deleted = self._backend.delete(ref=ref)
            if not deleted and not missing_ok:
                return failure(
                    meta=meta,
                    errors=[
                        not_found_error(
                            f"embedding not found for namespace='{ref.namespace}' key='{ref.key}'",
                            code=codes.RESOURCE_NOT_FOUND,
                        )
                    ],
                    payload=False,
                )
            return success(meta=meta, payload=deleted)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "embedding backend unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        retryable=True,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
                payload=False,
            )

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
        meta_errors = self._validate_meta(meta=meta)
        if meta_errors:
            return failure(meta=meta, errors=meta_errors, payload=[])

        if not namespace:
            return failure(
                meta=meta,
                errors=[validation_error("namespace is required", code=codes.MISSING_REQUIRED_FIELD)],
                payload=[],
            )

        if len(query_vector) == 0:
            return failure(
                meta=meta,
                errors=[validation_error("query_vector must not be empty", code=codes.INVALID_ARGUMENT)],
                payload=[],
            )

        effective_limit = self._settings.default_top_k if limit <= 0 else min(limit, self._settings.max_top_k)

        model_dimension = self._settings.model_dimensions.get(model)
        if model and model_dimension is not None and model_dimension != len(query_vector):
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        f"query vector dimension mismatch for model '{model}': expected {model_dimension}, got {len(query_vector)}",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
                payload=[],
            )

        try:
            collection_size = self._backend.get_collection_vector_size()
            if collection_size is not None and collection_size != len(query_vector):
                return failure(
                    meta=meta,
                    errors=[
                        validation_error(
                            f"query vector dimension mismatch for collection '{self._settings.collection_name}': expected {collection_size}, got {len(query_vector)}",
                            code=codes.INVALID_ARGUMENT,
                        )
                    ],
                    payload=[],
                )

            matches = self._backend.search(
                namespace=namespace,
                query_vector=query_vector,
                limit=effective_limit,
                model=model,
            )
            return success(meta=meta, payload=matches)
        except Exception as exc:  # noqa: BLE001
            return failure(
                meta=meta,
                errors=[
                    dependency_error(
                        "embedding backend unavailable",
                        code=codes.DEPENDENCY_UNAVAILABLE,
                        retryable=True,
                        metadata={"exception_type": type(exc).__name__},
                    )
                ],
                payload=[],
            )

    def _validate_ref_and_model(self, *, ref: EmbeddingRef, model: str) -> list[ErrorDetail]:
        """Validate reference/model input and return accumulated errors."""
        errors = self._validate_ref(ref=ref)
        if not model:
            errors.append(validation_error("model is required", code=codes.MISSING_REQUIRED_FIELD))
        elif self._settings.model_dimensions and model not in self._settings.model_dimensions:
            errors.append(
                validation_error(
                    f"unknown model '{model}'",
                    code=codes.INVALID_ARGUMENT,
                    metadata={"known_models": ",".join(sorted(self._settings.model_dimensions.keys()))},
                )
            )
        return errors

    def _validate_meta(self, *, meta: EnvelopeMeta) -> list[ErrorDetail]:
        """Validate required envelope metadata fields for service calls."""
        errors: list[ErrorDetail] = []
        if not meta.envelope_id:
            errors.append(validation_error("meta.envelope_id is required", code=codes.MISSING_REQUIRED_FIELD))
        if not meta.trace_id:
            errors.append(validation_error("meta.trace_id is required", code=codes.MISSING_REQUIRED_FIELD))
        if meta.timestamp is None:
            errors.append(validation_error("meta.timestamp is required", code=codes.MISSING_REQUIRED_FIELD))
        if meta.kind == EnvelopeKind.UNSPECIFIED:
            errors.append(validation_error("meta.kind must be specified", code=codes.INVALID_ARGUMENT))
        if not meta.source:
            errors.append(validation_error("meta.source is required", code=codes.MISSING_REQUIRED_FIELD))
        if not meta.principal:
            errors.append(validation_error("meta.principal is required", code=codes.MISSING_REQUIRED_FIELD))
        return errors

    def _validate_ref(self, *, ref: EmbeddingRef) -> list[ErrorDetail]:
        """Validate embedding reference fields and return accumulated errors."""
        errors: list[ErrorDetail] = []
        if not ref.namespace:
            errors.append(validation_error("ref.namespace is required", code=codes.MISSING_REQUIRED_FIELD))
        if not ref.key:
            errors.append(validation_error("ref.key is required", code=codes.MISSING_REQUIRED_FIELD))
        return errors
