"""Redis client construction helpers."""

from __future__ import annotations

from redis import Redis

from resources.substrates.redis.config import RedisSettings


def create_redis_client(settings: RedisSettings) -> Redis:
    """Construct a configured Redis client instance."""
    return create_redis_client_with_timeouts(
        settings=settings,
        connect_timeout_seconds=settings.connect_timeout_seconds,
        socket_timeout_seconds=settings.socket_timeout_seconds,
    )


def create_redis_client_with_timeouts(
    *,
    settings: RedisSettings,
    connect_timeout_seconds: float,
    socket_timeout_seconds: float,
) -> Redis:
    """Construct a Redis client instance with explicit timeout values."""
    return Redis.from_url(
        url=settings.url or "",
        socket_connect_timeout=connect_timeout_seconds,
        socket_timeout=socket_timeout_seconds,
        max_connections=settings.max_connections,
        decode_responses=True,
        encoding="utf-8",
    )
