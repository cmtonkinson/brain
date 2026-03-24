"""Tests for dashboard read-only data-source stubs."""

from __future__ import annotations

from packages.brain_dashboard.data_sources import (
    DockerDataSource,
    FileDataSource,
    LogDataSource,
    PostgresDataSource,
    RedisDataSource,
)


def test_postgres_data_source_returns_placeholder_views() -> None:
    """Postgres data source should return non-empty placeholder snapshots."""
    source = PostgresDataSource()

    assert source.fetch_health_items()
    assert source.fetch_active_trace().events
    assert source.fetch_turn_view().phase != ""
    assert source.fetch_policy_view().decision != ""


def test_other_data_sources_return_placeholder_state() -> None:
    """Other substrate readers should return non-empty placeholder data."""
    assert DockerDataSource().fetch_container_statuses()
    assert RedisDataSource().fetch_queue_depths()
    assert LogDataSource().fetch_recent_events()
    assert FileDataSource().list_known_log_files()
