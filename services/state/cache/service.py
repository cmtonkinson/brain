"""Authoritative in-process Python API for Cache Service."""

from __future__ import annotations

from abc import ABC, abstractmethod

from lib.shared.config import CoreRuntimeSettings
from lib.shared.envelope import Envelope, EnvelopeMeta
from resources.substrates.valkey import ValkeySubstrate
from services.state.cache.domain import (
    CacheEntry,
    HealthStatus,
    QueueDepth,
    QueueEntry,
    JsonValue,
)


class CacheService(ABC):
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
        """Return Cache and Valkey substrate readiness."""


def build_cache_service(
    *,
    settings: CoreRuntimeSettings,
    backend: ValkeySubstrate | None = None,
) -> CacheService:
    """Build default Cache implementation from typed settings."""
    from resources.substrates.valkey import (
        ValkeyClientSubstrate,
        resolve_valkey_settings,
    )
    from services.state.cache.config import resolve_cache_settings
    from services.state.cache.implementation import (
        DefaultCacheService,
    )

    return DefaultCacheService(
        settings=resolve_cache_settings(settings),
        backend=backend
        or ValkeyClientSubstrate(settings=resolve_valkey_settings(settings)),
    )
