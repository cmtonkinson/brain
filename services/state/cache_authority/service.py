"""Authoritative in-process Python API for Cache Authority Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from packages.brain_shared.config import CoreRuntimeSettings
from packages.brain_shared.envelope import Envelope, EnvelopeMeta
from resources.substrates.redis import RedisSubstrate
from services.state.cache_authority.domain import (
    CacheEntry,
    HealthStatus,
    QueueDepth,
    QueueEntry,
    JsonValue,
)


class CacheAuthorityService(ABC):
    """Public API for component-scoped cache and queue operations."""

    @abstractmethod
    def set_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
        value: JsonValue,
        ttl_seconds: int | None = None,
    ) -> Envelope[CacheEntry]:
        """Set one component-scoped cache value."""

    @abstractmethod
    def get_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
    ) -> Envelope[CacheEntry | None]:
        """Get one component-scoped cache value by key."""

    @abstractmethod
    def delete_value(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        key: str,
    ) -> Envelope[bool]:
        """Delete one component-scoped cache value."""

    @abstractmethod
    def push_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
        value: JsonValue,
    ) -> Envelope[QueueDepth]:
        """Push one component-scoped queue value."""

    @abstractmethod
    def pop_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
    ) -> Envelope[QueueEntry | None]:
        """Pop one component-scoped queue value using FIFO order."""

    @abstractmethod
    def peek_queue(
        self,
        *,
        meta: EnvelopeMeta,
        component_id: str,
        queue: str,
    ) -> Envelope[QueueEntry | None]:
        """Peek next component-scoped queue value without removal."""

    @abstractmethod
    def health(self, *, meta: EnvelopeMeta) -> Envelope[HealthStatus]:
        """Return CAS and Redis substrate readiness."""


def build_cache_authority_service(
    *,
    settings: CoreRuntimeSettings,
    backend: RedisSubstrate | None = None,
) -> CacheAuthorityService:
    """Build default Cache Authority implementation from typed settings."""
    from resources.substrates.redis import (
        RedisClientSubstrate,
        resolve_redis_settings,
    )
    from services.state.cache_authority.config import resolve_cache_authority_settings
    from services.state.cache_authority.implementation import (
        DefaultCacheAuthorityService,
    )

    return DefaultCacheAuthorityService(
        settings=resolve_cache_authority_settings(settings),
        backend=backend
        or RedisClientSubstrate(settings=resolve_redis_settings(settings)),
    )
