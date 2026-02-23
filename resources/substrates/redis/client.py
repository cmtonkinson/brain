"""Redis client construction helpers."""

from __future__ import annotations

from redis import Redis

from resources.substrates.redis.config import RedisSettings


def create_redis_client(settings: RedisSettings) -> Redis:
    """Construct a configured Redis client instance."""
    return Redis.from_url(
        url=settings.url or "",
        socket_connect_timeout=settings.connect_timeout_seconds,
        socket_timeout=settings.socket_timeout_seconds,
        max_connections=settings.max_connections,
        decode_responses=True,
        encoding="utf-8",
    )
