"""Valkey client-backed substrate implementation."""

from __future__ import annotations

from resources.substrates.valkey.client import (
    create_valkey_client,
    create_valkey_client_with_timeouts,
)
from resources.substrates.valkey.config import ValkeySettings
from resources.substrates.valkey.substrate import ValkeyHealthStatus, ValkeySubstrate


class ValkeyClientSubstrate(ValkeySubstrate):
    """Concrete Valkey substrate using valkey-py client operations."""

    def __init__(self, *, settings: ValkeySettings) -> None:
        self._client = create_valkey_client(settings)
        self._health_client = create_valkey_client_with_timeouts(
            settings=settings,
            connect_timeout_seconds=settings.health_timeout_seconds,
            socket_timeout_seconds=settings.health_timeout_seconds,
        )

    def set_value(self, *, key: str, value: str, ttl_seconds: int | None) -> None:
        """Set one serialized value with optional TTL in seconds."""
        if ttl_seconds is None:
            self._client.set(name=key, value=value)
            return
        self._client.set(name=key, value=value, ex=ttl_seconds)

    def get_value(self, *, key: str) -> str | None:
        """Get one serialized value by key or ``None`` when missing."""
        value = self._client.get(name=key)
        if value is None:
            return None
        return str(value)

    def delete_value(self, *, key: str) -> bool:
        """Delete one key and return whether a value was removed."""
        return bool(self._client.delete(key))

    def push_queue(self, *, queue: str, value: str) -> int:
        """Push one serialized value onto a queue and return resulting size."""
        return int(self._client.lpush(queue, value))

    def pop_queue(self, *, queue: str) -> str | None:
        """Pop one serialized value from queue tail (FIFO) or ``None`` when empty."""
        value = self._client.rpop(queue)
        if value is None:
            return None
        return str(value)

    def peek_queue(self, *, queue: str) -> str | None:
        """Peek next queue value to be popped or ``None`` when queue is empty."""
        value = self._client.lindex(queue, -1)
        if value is None:
            return None
        return str(value)

    def ping(self) -> bool:
        """Return substrate liveness from Valkey ``PING``."""
        return bool(self._health_client.ping())

    def health(self) -> ValkeyHealthStatus:
        """Probe Valkey substrate readiness and detail."""
        try:
            ready = self.ping()
        except Exception as exc:  # noqa: BLE001
            return ValkeyHealthStatus(
                ready=False,
                detail=f"valkey ping failed: {type(exc).__name__}",
            )
        return ValkeyHealthStatus(
            ready=ready,
            detail="ok" if ready else "valkey ping returned false",
        )
