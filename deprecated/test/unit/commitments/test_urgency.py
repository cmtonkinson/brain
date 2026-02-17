"""Unit tests for urgency calculation logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from commitments.urgency import compute_urgency


def test_example_high_importance_short_due_by() -> None:
    """Example calculation with high importance and near due_by."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    due_by = now + timedelta(hours=1)

    assert compute_urgency(importance=3, effort=1, due_by=due_by, now=now) == 67


def test_example_low_importance_long_due_by() -> None:
    """Example calculation with low importance and long time left."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    due_by = now + timedelta(days=30)

    assert compute_urgency(importance=1, effort=1, due_by=due_by, now=now) == 21


def test_null_due_by_defaults_to_seven_days() -> None:
    """Null due_by uses a seven-day default in the calculation."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)

    assert compute_urgency(importance=2, effort=2, due_by=None, now=now) == 41


def test_past_due_by_clamps_time_pressure() -> None:
    """Past due_by values clamp time pressure to 1.0."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    due_by = now - timedelta(hours=1)

    assert compute_urgency(importance=2, effort=2, due_by=due_by, now=now) == 80


def test_output_range_and_determinism() -> None:
    """Urgency is deterministic and always within the 1-100 range."""
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    due_by = now - timedelta(days=1)

    first = compute_urgency(importance=100, effort=100, due_by=due_by, now=now)
    second = compute_urgency(importance=100, effort=100, due_by=due_by, now=now)
    assert first == second
    assert first == 100

    low = compute_urgency(importance=-5, effort=-5, due_by=now + timedelta(days=3650), now=now)
    assert 1 <= low <= 100
