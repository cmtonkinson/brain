"""Concrete Cache Authority Service implementation."""

from __future__ import annotations

import json
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from packages.brain_shared.config import BrainSettings
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
    internal_error,
    validation_error,
)
from packages.brain_shared.logging import get_logger, public_api_instrumented
from resources.substrates.redis import (
    RedisClientSubstrate,
    RedisSubstrate,
    resolve_redis_settings,
)
from services.state.cache_authority.component import SERVICE_COMPONENT_ID
from services.state.cache_authority.config import (
    CacheAuthoritySettings,
    resolve_cache_authority_settings,
)
from services.state.cache_authority.domain import (
    CacheEntry,
    HealthStatus,
    JsonValue,
    QueueDepth,
    QueueEntry,
)
from services.state.cache_authority.service import CacheAuthorityService
from services.state.cache_authority.validation import (
    DeleteValueRequest,
    GetValueRequest,
    PeekQueueRequest,
    PopQueueRequest,
    PushQueueRequest,
    SetValueRequest,
)

_LOGGER = get_logger(__name__)


class DefaultCacheAuthorityService(CacheAuthorityService):
    """Default CAS implementation backed by Redis substrate resource."""

    def __init__(
        self,
        *,
        settings: CacheAuthoritySettings,
        backend: RedisSubstrate,
    ) -> None:
        self._settings = settings
        self._backend = backend

    @classmethod
    def from_settings(cls, settings: BrainSettings) -> "DefaultCacheAuthorityService":
        """Build CAS and owned Redis substrate from typed root settings."""
        service_settings = resolve_cache_authority_settings(settings)
        redis_settings = resolve_redis_settings(settings)
        return cls(
            settings=service_settings,
            backend=RedisClientSubstrate(settings=redis_settings),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "key"),
    )
    def set_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
        value: JsonValue,
        ttl_seconds: int | None = None,
    ) -> Envelope[CacheEntry]:
        """Set one component-scoped cache value with resolved TTL semantics."""
        request, errors = self._validate_request(
            meta=meta,
            model=SetValueRequest,
            payload={
                "component_id": component_id,
                "key": key,
                "value": value,
                "ttl_seconds": ttl_seconds,
            },
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        effective_ttl, ttl_error = self._resolve_ttl(request.ttl_seconds)
        if ttl_error is not None:
            return failure(meta=meta, errors=[ttl_error])

        redis_key = _cache_key(
            key_prefix=self._settings.key_prefix,
            component_id=request.component_id,
            key=request.key,
        )
        serialized = json.dumps(request.value)

        try:
            self._backend.set_value(
                key=redis_key,
                value=serialized,
                ttl_seconds=effective_ttl,
            )
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(meta=meta, operation="set_value", exc=exc)

        return success(
            meta=meta,
            payload=CacheEntry(
                component_id=request.component_id,
                key=request.key,
                value=request.value,
                ttl_seconds=effective_ttl,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "key"),
    )
    def get_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
    ) -> Envelope[CacheEntry | None]:
        """Get one component-scoped cache value by key."""
        request, errors = self._validate_request(
            meta=meta,
            model=GetValueRequest,
            payload={"component_id": component_id, "key": key},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        redis_key = _cache_key(
            key_prefix=self._settings.key_prefix,
            component_id=request.component_id,
            key=request.key,
        )
        try:
            serialized = self._backend.get_value(key=redis_key)
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(meta=meta, operation="get_value", exc=exc)

        if serialized is None:
            return success(meta=meta, payload=None)

        value, decode_error = _deserialize_json(serialized)
        if decode_error is not None:
            return failure(meta=meta, errors=[decode_error])

        return success(
            meta=meta,
            payload=CacheEntry(
                component_id=request.component_id,
                key=request.key,
                value=value,
                ttl_seconds=None,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "key"),
    )
    def delete_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
    ) -> Envelope[bool]:
        """Delete one component-scoped cache value."""
        request, errors = self._validate_request(
            meta=meta,
            model=DeleteValueRequest,
            payload={"component_id": component_id, "key": key},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        redis_key = _cache_key(
            key_prefix=self._settings.key_prefix,
            component_id=request.component_id,
            key=request.key,
        )
        try:
            deleted = self._backend.delete_value(key=redis_key)
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(
                meta=meta,
                operation="delete_value",
                exc=exc,
            )

        return success(meta=meta, payload=deleted)

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "queue"),
    )
    def push_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
        value: JsonValue,
    ) -> Envelope[QueueDepth]:
        """Push one component-scoped queue value."""
        request, errors = self._validate_request(
            meta=meta,
            model=PushQueueRequest,
            payload={"component_id": component_id, "queue": queue, "value": value},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        queue_key = _queue_key(
            key_prefix=self._settings.key_prefix,
            component_id=request.component_id,
            queue=request.queue,
        )
        serialized = json.dumps(request.value)

        try:
            size = self._backend.push_queue(queue=queue_key, value=serialized)
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(meta=meta, operation="push_queue", exc=exc)

        return success(
            meta=meta,
            payload=QueueDepth(
                component_id=request.component_id,
                queue=request.queue,
                size=size,
            ),
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "queue"),
    )
    def pop_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
    ) -> Envelope[QueueEntry | None]:
        """Pop one component-scoped queue value using FIFO order."""
        request, errors = self._validate_request(
            meta=meta,
            model=PopQueueRequest,
            payload={"component_id": component_id, "queue": queue},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        return self._read_queue_value(
            meta=meta,
            operation="pop_queue",
            reader=self._backend.pop_queue,
            component_id=request.component_id,
            queue=request.queue,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
        id_fields=("component_id", "queue"),
    )
    def peek_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
    ) -> Envelope[QueueEntry | None]:
        """Peek next component-scoped queue value without removal."""
        request, errors = self._validate_request(
            meta=meta,
            model=PeekQueueRequest,
            payload={"component_id": component_id, "queue": queue},
        )
        if errors:
            return failure(meta=meta, errors=errors)
        assert request is not None

        return self._read_queue_value(
            meta=meta,
            operation="peek_queue",
            reader=self._backend.peek_queue,
            component_id=request.component_id,
            queue=request.queue,
        )

    @public_api_instrumented(
        logger=_LOGGER,
        component_id=str(SERVICE_COMPONENT_ID),
    )
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return CAS-level readiness with shallow Redis ping probe."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return failure(
                meta=meta,
                errors=[validation_error(str(exc), code=codes.INVALID_ARGUMENT)],
            )

        try:
            substrate_ready = self._backend.ping()
        except Exception as exc:  # noqa: BLE001
            return success(
                meta=meta,
                payload=HealthStatus(
                    service_ready=True,
                    substrate_ready=False,
                    detail=str(exc) or "redis ping failed",
                ),
            )

        return success(
            meta=meta,
            payload=HealthStatus(
                service_ready=True,
                substrate_ready=bool(substrate_ready),
                detail="ok" if substrate_ready else "redis ping returned false",
            ),
        )

    def _validate_request(
        self,
        *,
        meta: EnvelopeMeta,
        model: type[BaseModel],
        payload: dict[str, Any],
    ) -> tuple[BaseModel | None, list[ErrorDetail]]:
        """Validate metadata and request payload with stable error messages."""
        try:
            validate_meta(meta)
        except ValueError as exc:
            return None, [validation_error(str(exc), code=codes.INVALID_ARGUMENT)]

        try:
            validated = model.model_validate(payload)
        except ValidationError as exc:
            issue = exc.errors()[0]
            field = ".".join(str(item) for item in issue.get("loc", ()))
            field_name = field if field else "payload"
            message = f"{field_name}: {issue.get('msg', 'invalid value')}"
            return None, [validation_error(message, code=codes.INVALID_ARGUMENT)]

        return validated, []

    def _resolve_ttl(
        self, ttl_seconds: int | None
    ) -> tuple[int | None, ErrorDetail | None]:
        """Resolve explicit/default/non-expiring TTL handling for set operations."""
        if ttl_seconds is None:
            return self._settings.default_ttl_seconds, None
        if ttl_seconds == 0:
            if not self._settings.allow_non_expiring_keys:
                return None, validation_error(
                    "ttl_seconds: non-expiring keys are disabled",
                    code=codes.INVALID_ARGUMENT,
                )
            return None, None
        return ttl_seconds, None

    def _dependency_failure(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        exc: Exception,
    ) -> Envelope[object]:
        """Map substrate exceptions into dependency-category envelope errors."""
        _LOGGER.warning(
            "CAS operation failed due to dependency error: operation=%s exception_type=%s",
            operation,
            type(exc).__name__,
            exc_info=exc,
        )
        return failure(
            meta=meta,
            errors=[
                dependency_error(
                    f"{operation} failed",
                    code=codes.DEPENDENCY_UNAVAILABLE,
                    metadata={
                        "resource": "substrate_redis",
                        "exception_type": type(exc).__name__,
                    },
                )
            ],
        )

    def _queue_envelope(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
        serialized: str | None,
    ) -> Envelope[QueueEntry | None]:
        """Build queue-entry response envelope from optional serialized payload."""
        if serialized is None:
            return success(meta=meta, payload=None)

        value, decode_error = _deserialize_json(serialized)
        if decode_error is not None:
            return failure(meta=meta, errors=[decode_error])

        return success(
            meta=meta,
            payload=QueueEntry(component_id=component_id, queue=queue, value=value),
        )

    def _read_queue_value(
        self,
        *,
        meta: EnvelopeMeta,
        operation: str,
        reader: Callable[..., str | None],
        component_id: str,
        queue: str,
    ) -> Envelope[QueueEntry | None]:
        """Read one queue payload from backend and map it to envelope result."""
        queue_key = _queue_key(
            key_prefix=self._settings.key_prefix,
            component_id=component_id,
            queue=queue,
        )
        try:
            serialized = reader(queue=queue_key)
        except Exception as exc:  # noqa: BLE001
            return self._dependency_failure(meta=meta, operation=operation, exc=exc)
        return self._queue_envelope(
            meta=meta,
            component_id=component_id,
            queue=queue,
            serialized=serialized,
        )


def _cache_key(*, key_prefix: str, component_id: str, key: str) -> str:
    """Compose canonical Redis key for component-scoped cache values."""
    return f"{key_prefix}:cache:{component_id}:{key}"


def _queue_key(*, key_prefix: str, component_id: str, queue: str) -> str:
    """Compose canonical Redis key for component-scoped queue values."""
    return f"{key_prefix}:queue:{component_id}:{queue}"


def _deserialize_json(serialized: str) -> tuple[JsonValue | None, ErrorDetail | None]:
    """Decode one JSON payload string into service JsonValue contract."""
    try:
        value = json.loads(serialized)
    except json.JSONDecodeError:
        return None, internal_error(
            "stored payload is not valid JSON",
            code=codes.INTERNAL_ERROR,
        )
    return value, None
