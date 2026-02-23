"""Repository-focused tests for OAS row datetime normalization strictness."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from services.state.object_authority.data.repository import _row_dt


def test_row_dt_rejects_missing_or_non_datetime_values() -> None:
    """Datetime extraction must fail fast on malformed row values."""
    with pytest.raises(ValueError, match="expected datetime column for created_at"):
        _row_dt({}, "created_at")

    with pytest.raises(ValueError, match="expected datetime column for created_at"):
        _row_dt({"created_at": "2026-02-23T00:00:00Z"}, "created_at")


def test_row_dt_normalizes_naive_and_aware_datetimes_to_utc() -> None:
    """Datetime extraction should normalize valid values to UTC-aware timestamps."""
    naive = datetime(2026, 2, 23, 12, 0, 0)
    aware = datetime(2026, 2, 23, 12, 0, 0, tzinfo=UTC)

    normalized_naive = _row_dt({"created_at": naive}, "created_at")
    normalized_aware = _row_dt({"created_at": aware}, "created_at")

    assert normalized_naive.tzinfo == UTC
    assert normalized_aware.tzinfo == UTC
