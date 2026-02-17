"""Integration tests for commitment review run tracking."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from commitments.review_aggregation import (
    DEFAULT_REVIEW_EPOCH,
    get_last_review_run_at,
    record_review_run,
)
from config import settings
from services import database


def _ensure_database_ready() -> None:
    """Skip tests when the integration database is not configured or reachable."""
    if not settings.database.url and not settings.database.postgres_password:
        pytest.skip("Integration DB not configured (set DATABASE_URL or POSTGRES_PASSWORD).")
    try:
        with database.get_sync_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Integration DB not reachable: {exc}")


def test_review_run_tracking_round_trip() -> None:
    """Review run records should persist and update the last run timestamp."""
    _ensure_database_ready()
    database.run_migrations_sync()

    last_run = get_last_review_run_at(database.get_sync_session)
    assert last_run == DEFAULT_REVIEW_EPOCH

    now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    record_review_run(database.get_sync_session, run_at=now)

    updated = get_last_review_run_at(database.get_sync_session)
    assert updated == now
