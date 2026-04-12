"""Tests for dashboard data source connection skeletons."""

from __future__ import annotations

from unittest.mock import patch


from packages.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from packages.dashboard.data_sources.redis import (
    BaseRedisDataSource,
    RedisConnectionConfig,
)
from packages.dashboard.models.data_source import RetentionPolicy

_RETENTION = RetentionPolicy(family="snapshot", max_items=10)


def test_postgres_config_defaults():
    cfg = PostgresConnectionConfig(url="postgresql://x:y@localhost/db")
    assert cfg.pool_size == 3
    assert cfg.read_only is True


def test_redis_config_defaults():
    cfg = RedisConnectionConfig()
    assert cfg.url == "redis://localhost:6379/0"
    assert cfg.read_only is True


def test_postgres_fetch_error_captured():
    cfg = PostgresConnectionConfig(url="postgresql://bad:bad@localhost/bad")
    src = BasePostgresDataSource(config=cfg, poll_interval=1.0, retention=_RETENTION)
    with patch("psycopg.connect", side_effect=Exception("conn refused")):
        src._poll_once()
    snap = src.get_snapshot()
    assert snap.stale is True
    assert snap.error is not None


def test_redis_fetch_error_captured():
    cfg = RedisConnectionConfig(url="redis://bad:6379/0")
    src = BaseRedisDataSource(config=cfg, poll_interval=1.0, retention=_RETENTION)
    with patch("redis.Redis.from_url", side_effect=Exception("no redis")):
        src._poll_once()
    snap = src.get_snapshot()
    assert snap.stale is True
    assert snap.error is not None
