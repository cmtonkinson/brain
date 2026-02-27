"""Concrete Object Authority Service implementation."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import (
    Envelope,
    EnvelopeMeta,
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
from resources.substrates.filesystem import (
    FilesystemBlobSubstrate,
    LocalFilesystemBlobSubstrate,
    resolve_filesystem_substrate_settings,
)
from resources.substrates.postgres.errors import normalize_postgres_error
from services.state.object_authority.component import SERVICE_COMPONENT_ID
from services.state.object_authority.config import (
    ObjectAuthoritySettings,
    resolve_object_authority_settings,
)
from services.state.object_authority.data import (
    ObjectPostgresRuntime,
    PostgresObjectRepository,
)
from services.state.object_authority.domain import (
    HealthStatus,
    ObjectGetResult,
    ObjectRecord,
)
from services.state.object_authority.interfaces import ObjectRepository
from services.state.object_authority.service import ObjectAuthorityService
from services.state.object_authority.validation import (
    ObjectKeyRequest,
    PutObjectRequest,
)

_LOGGER = get_logger(__name__)


class DefaultObjectAuthorityService(ObjectAuthorityService):
    """Default OAS implementation with Postgres authority and filesystem blobs."""

    def __init__(
        self,
        *,
        settings: ObjectAuthoritySettings,
        repository: ObjectRepository,
        blob_store: FilesystemBlobSubstrate,
        default_extension: str,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._blob_store = blob_store
        self._default_extension = default_extension

    @classmethod
    def from_settings(
        cls, settings: CoreRuntimeSettings
    ) -> "DefaultObjectAuthorityService":
        """Build OAS from typed settings and owned resources."""
        service_settings = resolve_object_authority_settings(settings)
        fs_settings = resolve_filesystem_substrate_settings(settings)
        runtime = ObjectPostgresRuntime.from_settings(settings)
        return cls(
            settings=service_settings,
            repository=PostgresObjectRepository(runtime.schema_sessions),
            blob_store=LocalFilesystemBlobSubstrate(settings=fs_settings),
            default_extension=fs_settings.default_extension,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return OAS readiness based on owned Postgres repository availability."""
        validate_meta(meta)
        try:
            self._repository.get_object_by_key(object_key="__brain_health_check__")
        except Exception as exc:  # noqa: BLE001
            if _is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="health", exc=exc)
        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                substrate_ready=True,
                detail="ok",
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
    ) -> Envelope[ObjectRecord]:
        """Persist one blob and return authoritative metadata record."""
        request, errors = self._validate_request(
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
                self._blob_store.write_blob(
                    digest_hex=existing.metadata.digest_hex,
                    extension=existing.metadata.extension,
                    content=request.content,
                )
                return success(meta=meta, payload=existing)
        except Exception as exc:  # noqa: BLE001
            if _is_postgres_error(exc):
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
            if _is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="put_object", exc=exc)
        return success(meta=meta, payload=created)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("object_key",),
    )
    def get_object(
        self, *, meta: EnvelopeMeta, object_key: str
    ) -> Envelope[ObjectGetResult]:
        """Read one blob and metadata by object key."""
        request, errors = self._validate_request(
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
            if _is_postgres_error(exc):
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
        request, errors = self._validate_request(
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
            if _is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(meta=meta, operation="stat_object", exc=exc)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("object_key",),
    )
    def delete_object(self, *, meta: EnvelopeMeta, object_key: str) -> Envelope[bool]:
        """Delete one object and return idempotent success."""
        request, errors = self._validate_request(
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
            if _is_postgres_error(exc):
                return failure(meta=meta, errors=[normalize_postgres_error(exc)])
            return self._dependency_failure(
                meta=meta, operation="delete_object", exc=exc
            )

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any] | None,
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate envelope metadata and request payload model."""
        errors = validate_meta(meta)
        if errors:
            return None, errors

        data = payload or {}
        try:
            request = model.model_validate(data)
        except ValidationError as exc:
            return None, [
                validation_error(
                    f"request validation failed: {err['msg']}",
                    code=codes.INVALID_ARGUMENT,
                    metadata={"field": ".".join(str(p) for p in err["loc"])},
                )
                for err in exc.errors()
            ]

        return request, []

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
                    metadata={"exception_type": type(exc).__name__},
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
    seeded = b"b1:\0" + content
    return hashlib.sha256(seeded).hexdigest()


def _format_object_key(*, version: str, algorithm: str, digest_hex: str) -> str:
    """Format canonical object key for one digest identity tuple."""
    return f"{version}:{algorithm}:{digest_hex}"


def _is_postgres_error(exc: Exception) -> bool:
    """Return whether one exception appears to originate from Postgres stack."""
    module = type(exc).__module__
    return module.startswith("sqlalchemy") or module.startswith("psycopg")
