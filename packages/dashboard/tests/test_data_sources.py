"""Tests for dashboard data source connection skeletons."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from packages.dashboard.data_sources.postgres import (
    BasePostgresDataSource,
    PostgresConnectionConfig,
)
from packages.dashboard.data_sources.redis import (
    BaseRedisDataSource,
    RedisConnectionConfig,
)
from packages.dashboard.data_sources.traces import _build_trace_tree
from packages.dashboard.data_sources.turns import (
    _build_current_turn,
    _build_recent_turns,
)
from packages.dashboard.models.data_source import RetentionPolicy

_RETENTION = RetentionPolicy(family="snapshot", max_items=10)


def _dt(minutes: int) -> datetime:
    return datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_postgres_config_defaults():
    cfg = PostgresConnectionConfig(url="postgresql://x:y@localhost/db")
    assert cfg.pool_size == 3
    assert cfg.read_only is True


def test_redis_config_defaults():
    cfg = RedisConnectionConfig()
    assert cfg.url == "redis://localhost:8761/0"
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


def test_build_current_turn_pairs_latest_inbound_with_following_outbound():
    rows = [
        (
            "out-1",
            "session-1",
            "outbound",
            "Sure. I've drafted the reply.",
            "claude-sonnet-4",
            "anthropic",
            1842,
            "standard",
            "trace-1",
            "agent",
            _dt(2),
        ),
        (
            "in-1",
            "session-1",
            "inbound",
            "Can you draft a reply?",
            "",
            "",
            None,
            None,
            "trace-1",
            "operator",
            _dt(1),
        ),
    ]

    current = _build_current_turn(rows)
    assert current is not None
    assert current.state == "complete"
    assert current.response_content == "Sure. I've drafted the reply."
    assert current.model == "claude-sonnet-4"
    assert current.reasoning_level == "standard"


def test_build_current_turn_marks_pending_without_outbound():
    rows = [
        (
            "in-1",
            "session-1",
            "inbound",
            "Can you draft a reply?",
            "",
            "",
            None,
            None,
            "trace-1",
            "operator",
            _dt(1),
        ),
    ]

    current = _build_current_turn(rows)
    assert current is not None
    assert current.state == "pending"
    assert current.response_content is None
    assert current.elapsed_ms is not None


def test_build_recent_turns_normalizes_direction_and_summary():
    recent = _build_recent_turns(
        [
            (
                "turn-1",
                "session-1",
                "inbound",
                "Need a summary of today's notes",
                "",
                "",
                None,
                None,
                "trace-1",
                "operator",
                _dt(0),
            )
        ]
    )

    assert len(recent) == 1
    assert recent[0].direction == "in"
    assert "summary of today's notes" in recent[0].summary


def test_build_trace_tree_uses_parent_linkage():
    roots = _build_trace_tree(
        [
            {
                "envelope_id": "root",
                "parent_id": None,
                "component": "switchboard",
                "operation": "ingest_signal",
                "status": "OK",
                "source": "switchboard",
                "principal": "operator",
                "elapsed_ms": 10,
                "timestamp": _dt(0),
            },
            {
                "envelope_id": "child",
                "parent_id": "root",
                "component": "agent",
                "operation": "process_instruction",
                "status": "OK",
                "source": "agent",
                "principal": "operator",
                "elapsed_ms": 20,
                "timestamp": _dt(1),
            },
            {
                "envelope_id": "grandchild",
                "parent_id": "child",
                "component": "policy",
                "operation": "authorize",
                "status": "DENIED",
                "source": "policy",
                "principal": "operator",
                "elapsed_ms": 5,
                "timestamp": _dt(2),
            },
        ]
    )

    assert len(roots) == 1
    assert roots[0].envelope_id == "root"
    assert roots[0].children[0].envelope_id == "child"
    assert roots[0].children[0].children[0].envelope_id == "grandchild"
