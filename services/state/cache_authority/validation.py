"""Request validation models for Cache Authority Service public API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.brain_shared.manifest import ComponentId, validate_component_id
from services.state.cache_authority.domain import JsonValue


def _strip_text(value: object) -> object:
    """Normalize surrounding whitespace for textual request fields."""
    if isinstance(value, str):
        return value.strip()
    return value


def _require_component_id(value: str) -> str:
    """Require one valid canonical component identifier string."""
    validate_component_id(ComponentId(value))
    return value


class _ScopedKeyRequest(BaseModel):
    """Base request carrying component-scoped identifiers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str

    @field_validator("component_id", mode="before")
    @classmethod
    def _strip_text(cls, value: object) -> object:
        """Normalize surrounding whitespace for component text fields."""
        return _strip_text(value)

    @field_validator("component_id")
    @classmethod
    def _validate_component_id(cls, value: str) -> str:
        """Validate canonical component id format."""
        return _require_component_id(value)


class _ScopedCacheRequest(_ScopedKeyRequest):
    """Base request carrying component-scoped cache key identifiers."""

    key: str = Field(min_length=1)

    @field_validator("key", mode="before")
    @classmethod
    def _strip_key(cls, value: object) -> object:
        """Normalize surrounding whitespace for cache key fields."""
        return _strip_text(value)


class SetValueRequest(_ScopedCacheRequest):
    """Validate one set-value request payload."""

    value: JsonValue
    ttl_seconds: int | None = Field(default=None, ge=0)


class GetValueRequest(_ScopedCacheRequest):
    """Validate one get-value request payload."""


class DeleteValueRequest(_ScopedCacheRequest):
    """Validate one delete-value request payload."""


class _ScopedQueueRequest(_ScopedKeyRequest):
    """Base request carrying component-scoped queue identifiers."""

    queue: str = Field(min_length=1)

    @field_validator("queue", mode="before")
    @classmethod
    def _strip_queue(cls, value: object) -> object:
        """Normalize surrounding whitespace for queue text fields."""
        return _strip_text(value)


class PushQueueRequest(_ScopedQueueRequest):
    """Validate one queue-push request payload."""

    value: JsonValue


class PopQueueRequest(_ScopedQueueRequest):
    """Validate one queue-pop request payload."""


class PeekQueueRequest(_ScopedQueueRequest):
    """Validate one queue-peek request payload."""
