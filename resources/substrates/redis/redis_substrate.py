"""Redis client-backed substrate implementation."""

from __future__ import annotations

from resources.substrates.redis.client import create_redis_client
from resources.substrates.redis.config import RedisSettings
from resources.substrates.redis.substrate import RedisSubstrate


class RedisClientSubstrate(RedisSubstrate):
    """Concrete Redis substrate using redis-py client operations."""

    def __init__(self, *, settings: RedisSettings) -> None:
        self._client = create_redis_client(settings)

    def set_value(self, *, key: str, value: str, ttl_seconds: int | None) -> None:
        """Set one value with optional TTL in seconds."""
        if ttl_seconds is None:
            self._client.set(name=key, value=value)
            return
        self._client.set(name=key, value=value, ex=ttl_seconds)

    def get_value(self, *, key: str) -> str | None:
        """Read one value by key."""
        value = self._client.get(name=key)
        if value is None:
            return None
        return str(value)

    def delete_value(self, *, key: str) -> bool:
        """Delete one key and return whether a value existed."""
        return bool(self._client.delete(key))

    def push_queue(self, *, queue: str, value: str) -> int:
        """Push one value at queue head and return resulting queue size."""
        return int(self._client.lpush(queue, value))

    def pop_queue(self, *, queue: str) -> str | None:
        """Pop one value from queue tail for FIFO semantics."""
        value = self._client.rpop(queue)
        if value is None:
            return None
        return str(value)

    def peek_queue(self, *, queue: str) -> str | None:
        """Peek next value from queue tail without removing it."""
        value = self._client.lindex(queue, -1)
        if value is None:
            return None
        return str(value)

    def ping(self) -> bool:
        """Return Redis ping status."""
        return bool(self._client.ping())
