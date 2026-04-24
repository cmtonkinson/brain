"""Retry policy logic for Job Service execution attempts."""

from __future__ import annotations

from datetime import datetime, timedelta

from services.reason.job.domain import BackoffStrategy


def should_retry(attempt_number: int, max_attempts: int) -> bool:
    """Return ``True`` when another retry attempt is allowed."""
    return attempt_number < max_attempts


def compute_backoff_delay_seconds(
    strategy: BackoffStrategy,
    retry_count: int,
    base_seconds: int,
) -> int:
    """Compute the delay in seconds before the next retry attempt.

    ``retry_count`` is the 1-based retry number (first retry = 1).
    """
    if retry_count <= 0:
        msg = "retry_count must be >= 1"
        raise ValueError(msg)
    if base_seconds < 0:
        msg = "base_seconds must be >= 0"
        raise ValueError(msg)

    if strategy == BackoffStrategy.none:
        return 0
    if strategy == BackoffStrategy.fixed:
        return base_seconds
    if strategy == BackoffStrategy.exponential:
        return base_seconds * (2 ** (retry_count - 1))

    msg = f"unsupported backoff strategy: {strategy}"
    raise ValueError(msg)


def compute_retry_at(
    finished_at: datetime,
    retry_count: int,
    *,
    strategy: BackoffStrategy,
    base_seconds: int,
) -> datetime:
    """Return the datetime at which the next retry should be attempted."""
    delay = compute_backoff_delay_seconds(strategy, retry_count, base_seconds)
    return finished_at + timedelta(seconds=delay)
