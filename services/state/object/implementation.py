"""Concrete Object Service implementation."""

from __future__ import annotations

import hashlib
from typing import Any

from lib.shared.envelope import (
    Envelope,
    EnvelopeMeta,
    failure,
    success,
    validate_meta,
    validate_service_request,
)
from lib.shared.errors import (
    codes,
    dependency_error,
    not_found_error,
    validation_error,
)
from lib.shared.logging import get_logger, public_api_instrumented
from resources.substrates.seaweedfs import BlobSubstrate
from resources.substrates.postgres.errors import (
    is_postgres_error,
    normalize_postgres_error,
)
from services.state.object.component import SERVICE_COMPONENT_ID
from services.state.object.config import ObjectSettings
from services.state.object.domain import (
    HealthStatus,
    ObjectGetResult,
    ObjectPutResult,
    ObjectRecord,
    ObjectWriteDisposition,
)
from services.state.object.interfaces import ObjectRepository
from services.state.object.service import ObjectService
from services.state.object.validation import (
    ObjectKeyRequest,
    PutObjectRequest,
)

_LOGGER = get_logger(__name__)


class DefaultObjectService(ObjectService):
    """Default Object implementation with Postgres-backed state and SeaweedFS blobs."""

    def __init__(
        self,
        *,
        settings: ObjectSettings,
        repository: ObjectRepository,
        blob_store: BlobSubstrate,
        default_extension: str,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._blob_store = blob_store
        self._default_extension = default_extension

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return Object readiness based on owned repository and substrate availability."""
        validate_meta(meta)
        try:
            self._repository.get_object_by_key(object_key="__brain_health_check__")
            substrate_health = self._blob_store.health()
        except Exception as exc:  # noqa: BLE001
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="health", exc=exc)
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                substrate_ready=substrate_health.ready,
                detail=substrate_health.detail,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def put_object(
        self,
        *,
        meta: EnvelopeMeta,
        content: bytes,
        extension: str,
        content_type: str,
        original_filename: str,
        source_uri: str,
    ) -> Envelope[ObjectPutResult]:
        """Persist one blob and return metadata plus dedupe disposition."""
        request, errors = validate_service_request(
            meta=meta,
            model=PutObjectRequest,
            payload={
                "content": content,
                "extension": extension or self._default_extension,
                "content_type": content_type,
                "original_filename": original_filename,
                "source_uri": source_uri,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        if len(request.content) > self._settings.max_blob_size_bytes:
            return failure(
                meta=meta,
                errors=[
                    validation_error(
                        "content exceeds max_blob_size_bytes",
                        code=codes.INVALID_ARGUMENT,
                    )
                ],
            )

        digest_hex = _digest_payload(request.content)
        object_key = _format_object_key(
            version=self._settings.digest_version,
            algorithm=self._settings.digest_algorithm,
            digest_hex=digest_hex,
        )

        try:
            existing = self._repository.get_object_by_key(object_key=object_key)
            if existing is not None:
                return success(
                    meta=meta,
                    payload=ObjectPutResult(
                        object=existing,
                        write_disposition=ObjectWriteDisposition.existing,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="put_object", exc=exc)

        try:
            self._blob_store.write_blob(
                digest_hex=digest_hex,
                extension=request.extension,
                content=request.content,
            )
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(meta=meta, operation="put_object", exc=exc)
        try:
            created = self._repository.upsert_object(
                object_key=object_key,
                digest_algorithm=self._settings.digest_algorithm,
                digest_version=self._settings.digest_version,
                digest_hex=digest_hex,
                extension=request.extension,
                content_type=request.content_type,
                size_bytes=len(request.content),
                original_filename=request.original_filename,
                source_uri=request.source_uri,
            )
        except Exception as exc:  # noqa: BLE001
            self._cleanup_orphaned_blob(
                object_key=object_key,
                digest_hex=digest_hex,
                extension=request.extension,
            )
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="put_object", exc=exc)
        return success(
            meta=meta,
            payload=ObjectPutResult(
                object=created,
                write_disposition=ObjectWriteDisposition.created,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("object_key",),
    )
    def get_object(
        self, *, meta: EnvelopeMeta, object_key: str
    ) -> Envelope[ObjectGetResult]:
        """Read one blob and metadata by object key."""
        request, errors = validate_service_request(
            meta=meta,
            model=ObjectKeyRequest,
            payload={"object_key": object_key},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._repository.get_object_by_key(object_key=request.object_key)
            if record is None:
                return self._not_found(meta=meta, object_key=request.object_key)

            content = self._blob_store.read_blob(
                digest_hex=record.metadata.digest_hex,
                extension=record.metadata.extension,
            )
            return success(
                meta=meta, payload=ObjectGetResult(object=record, content=content)
            )
        except FileNotFoundError:
            return self._not_found(meta=meta, object_key=request.object_key)
        except Exception as exc:  # noqa: BLE001
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="get_object", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("object_key",),
    )
    def stat_object(
        self, *, meta: EnvelopeMeta, object_key: str
    ) -> Envelope[ObjectRecord]:
        """Read metadata for one object key."""
        request, errors = validate_service_request(
            meta=meta,
            model=ObjectKeyRequest,
            payload={"object_key": object_key},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._repository.get_object_by_key(object_key=request.object_key)
            if record is None:
                return self._not_found(meta=meta, object_key=request.object_key)
            return success(meta=meta, payload=record)
        except Exception as exc:  # noqa: BLE001
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="stat_object", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("object_key",),
    )
    def delete_object(self, *, meta: EnvelopeMeta, object_key: str) -> Envelope[bool]:
        """Delete one object and return idempotent success."""
        request, errors = validate_service_request(
            meta=meta,
            model=ObjectKeyRequest,
            payload={"object_key": object_key},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        try:
            record = self._repository.get_object_by_key(object_key=request.object_key)
            if record is None:
                return success(meta=meta, payload=True)

            try:
                self._blob_store.delete_blob(
                    digest_hex=record.metadata.digest_hex,
                    extension=record.metadata.extension,
                )
            except FileNotFoundError:
                pass

            self._repository.delete_object_by_key(object_key=request.object_key)
            return success(meta=meta, payload=True)
        except Exception as exc:  # noqa: BLE001
            if is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(
                meta=meta, operation="delete_object", exc=exc
            )

    def _not_found(self, *, meta: EnvelopeMeta, object_key: str) -> Envelope[Any]:
        """Return canonical not-found envelope for object-key lookups."""
        return failure(
            meta=meta,
            errors=[
                not_found_error(
                    "object not found",
                    code=codes.RESOURCE_NOT_FOUND,
                    metadata={"object_key": object_key},
                )
            ],
        )

    def _dependency_failure(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        exc: Exception,
    ) -> Envelope[Any]:
        """Map one dependency/runtime exception into structured envelope errors."""
        _LOGGER.warning(
            "%s failed due to dependency error: exception_type=%s",
            operation,
            type(exc).__name__,
            exc_info=exc,
        )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    f"{operation} failed",
                    code=codes.DEPENDENCY_FAILURE,
                    metadata={codes.EXCEPTION_TYPE_KEY: type(exc).__name__},
                )
            ],
        )

    def _cleanup_orphaned_blob(
        self,
        *,
        object_key: str,
        digest_hex: str,
        extension: str,
    ) -> None:
        """Best-effort cleanup for blobs written before metadata upsert failure."""
        try:
            if self._repository.get_object_by_key(object_key=object_key) is not None:
                return
        except Exception:  # noqa: BLE001
            return
        try:
            self._blob_store.delete_blob(digest_hex=digest_hex, extension=extension)
        except FileNotFoundError:
            return
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to clean orphaned blob: object_key=%s exception_type=%s",
                object_key,
                type(exc).__name__,
                exc_info=exc,
            )


def _digest_payload(content: bytes) -> str:
    """Return deterministic digest hex using prototype seeded hash semantics."""
    seeded = (
        b"b1:\0" + content
    )  # b1:\x00 — null byte ensures no valid UTF-8 prefix collides with "b1:" in plain string space
    return hashlib.sha256(seeded).hexdigest()


def _format_object_key(*, version: str, algorithm: str, digest_hex: str) -> str:
    """Format canonical object key for one digest identity tuple."""
    return f"{version}:{algorithm}:{digest_hex}"
