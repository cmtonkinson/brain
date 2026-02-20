"""Repository-focused tests for EAS row mapping strictness and normalization."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services.state.embedding_authority.data.repository import _row_dt


def test_row_dt_rejects_missing_or_non_datetime_values() -> None:
    """Repository row datetime extraction must fail fast on malformed values."""
    with pytest.raises(ValueError, match="expected datetime column for created_at"):
        _row_dt({}, "created_at")

    with pytest.raises(ValueError, match="expected datetime column for created_at"):
        _row_dt({"created_at": "2026-02-20T00:00:00Z"}, "created_at")


def test_row_dt_normalizes_naive_and_aware_datetimes_to_utc() -> None:
    """Datetime extraction should normalize valid values to UTC-aware datetimes."""
    naive = datetime(2026, 2, 20, 10, 30, 0)
    aware = datetime(2026, 2, 20, 10, 30, 0, tzinfo=UTC)

    normalized_naive = _row_dt({"created_at": naive}, "created_at")
    normalized_aware = _row_dt({"created_at": aware}, "created_at")

    assert normalized_naive.tzinfo == UTC
    assert normalized_aware.tzinfo == UTC
