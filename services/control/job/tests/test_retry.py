"""Tests for Job Service retry policy logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.control.job.domain import BackoffStrategy
from services.control.job.retry import (
    compute_backoff_delay_seconds,
    compute_retry_at,
    should_retry,
)

_UTC = timezone.utc


class TestShouldRetry:
    """Attempt limit enforcement."""

    def test_allows_retry_below_max(self) -> None:
        assert should_retry(attempt_number=1, max_attempts=3) is True
        assert should_retry(attempt_number=2, max_attempts=3) is True

    def test_denies_retry_at_max(self) -> None:
        assert should_retry(attempt_number=3, max_attempts=3) is False

    def test_denies_retry_above_max(self) -> None:
        assert should_retry(attempt_number=5, max_attempts=3) is False


class TestBackoffDelay:
    """Backoff strategy delay computation."""

    def test_none_returns_zero(self) -> None:
        assert compute_backoff_delay_seconds(BackoffStrategy.none, 1, 60) == 0

    def test_fixed_returns_base(self) -> None:
        assert compute_backoff_delay_seconds(BackoffStrategy.fixed, 1, 60) == 60
        assert compute_backoff_delay_seconds(BackoffStrategy.fixed, 3, 60) == 60

    def test_exponential_doubles(self) -> None:
        assert compute_backoff_delay_seconds(BackoffStrategy.exponential, 1, 30) == 30
        assert compute_backoff_delay_seconds(BackoffStrategy.exponential, 2, 30) == 60
        assert compute_backoff_delay_seconds(BackoffStrategy.exponential, 3, 30) == 120

    def test_exponential_with_zero_base(self) -> None:
        assert compute_backoff_delay_seconds(BackoffStrategy.exponential, 1, 0) == 0

    def test_retry_count_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="retry_count must be >= 1"):
            compute_backoff_delay_seconds(BackoffStrategy.fixed, 0, 60)

    def test_negative_base_raises(self) -> None:
        with pytest.raises(ValueError, match="base_seconds must be >= 0"):
            compute_backoff_delay_seconds(BackoffStrategy.fixed, 1, -1)


class TestComputeRetryAt:
    """Retry-at timestamp computation."""

    def test_applies_delay(self) -> None:
        finished = datetime(2026, 1, 1, 12, 0, 0, tzinfo=_UTC)
        result = compute_retry_at(
            finished, 1, strategy=BackoffStrategy.fixed, base_seconds=60
        )
        assert result == finished + timedelta(seconds=60)

    def test_exponential_delay(self) -> None:
        finished = datetime(2026, 1, 1, 12, 0, 0, tzinfo=_UTC)
        result = compute_retry_at(
            finished, 3, strategy=BackoffStrategy.exponential, base_seconds=30
        )
        assert result == finished + timedelta(seconds=120)

    def test_none_delay(self) -> None:
        finished = datetime(2026, 1, 1, 12, 0, 0, tzinfo=_UTC)
        result = compute_retry_at(
            finished, 1, strategy=BackoffStrategy.none, base_seconds=60
        )
        assert result == finished
