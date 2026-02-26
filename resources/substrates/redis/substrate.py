"""Transport-agnostic substrate contract for Redis-backed operations."""

from __future__ import annotations

from typing import Protocol
from pydantic import BaseModel, ConfigDict


class RedisHealthStatus(BaseModel):
    """Redis substrate readiness payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ready: bool
    detail: str


class RedisSubstrate(Protocol):
    """Protocol for direct Redis cache and queue operations."""

    def set_value(self, *, key: str, value: str, ttl_seconds: int | None) -> None:
        """Set one serialized value with optional TTL in seconds."""

    def get_value(self, *, key: str) -> str | None:
        """Get one serialized value by key or ``None`` when missing."""

    def delete_value(self, *, key: str) -> bool:
        """Delete one key and return whether a value was removed."""

    def push_queue(self, *, queue: str, value: str) -> int:
        """Push one serialized value onto a queue and return resulting size."""

    def pop_queue(self, *, queue: str) -> str | None:
        """Pop one serialized value from queue tail (FIFO) or ``None`` when empty."""

    def peek_queue(self, *, queue: str) -> str | None:
        """Peek next queue value to be popped or ``None`` when queue is empty."""

    def ping(self) -> bool:
        """Return substrate liveness from Redis ``PING``."""

    def health(self) -> RedisHealthStatus:
        """Probe Redis substrate readiness and detail."""
