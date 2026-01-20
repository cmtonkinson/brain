"""Unit tests for scheduler retry policy helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scheduler.retry_policy import compute_backoff_delay_seconds, compute_retry_at, should_retry


def test_should_retry_respects_max_attempts() -> None:
    """Ensure retry allowance honors max attempts."""
    assert should_retry(1, 3) is True
    assert should_retry(2, 3) is True
    assert should_retry(3, 3) is False


def test_compute_backoff_delay_fixed() -> None:
    """Ensure fixed backoff returns the base delay."""
    delay = compute_backoff_delay_seconds("fixed", retry_count=2, backoff_base_seconds=60)
    assert delay == 60


def test_compute_backoff_delay_exponential() -> None:
    """Ensure exponential backoff scales with retry count."""
    first = compute_backoff_delay_seconds("exponential", retry_count=1, backoff_base_seconds=30)
    second = compute_backoff_delay_seconds("exponential", retry_count=2, backoff_base_seconds=30)
    third = compute_backoff_delay_seconds("exponential", retry_count=3, backoff_base_seconds=30)
    assert first == 30
    assert second == 60
    assert third == 120


def test_compute_backoff_delay_none() -> None:
    """Ensure none backoff returns a zero delay."""
    delay = compute_backoff_delay_seconds("none", retry_count=1, backoff_base_seconds=10)
    assert delay == 0


def test_compute_retry_at_applies_delay() -> None:
    """Ensure retry timestamp includes the computed delay."""
    finished_at = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    retry_at = compute_retry_at(
        finished_at,
        retry_count=2,
        backoff_strategy="fixed",
        backoff_base_seconds=90,
    )
    assert retry_at == finished_at + timedelta(seconds=90)
