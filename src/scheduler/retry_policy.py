"""Retry and backoff policy helpers for scheduled executions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from config import settings
from models import BackoffStrategyEnum


@dataclass(frozen=True)
class RetryPolicy:
    """Retry/backoff configuration for scheduled executions."""

    max_attempts: int
    backoff_strategy: str
    backoff_base_seconds: int

    @staticmethod
    def from_settings() -> "RetryPolicy":
        """Build a retry policy from scheduler settings."""
        scheduler_config = settings.scheduler
        return RetryPolicy(
            max_attempts=int(scheduler_config.default_max_attempts),
            backoff_strategy=str(scheduler_config.default_backoff_strategy),
            backoff_base_seconds=int(scheduler_config.backoff_base_seconds),
        )


def resolve_retry_policy(policy: RetryPolicy | None) -> RetryPolicy:
    """Return a validated retry policy, defaulting to settings when unset."""
    resolved = policy or RetryPolicy.from_settings()
    _validate_policy(resolved)
    return resolved


def should_retry(attempt_count: int, max_attempts: int) -> bool:
    """Return whether another retry attempt is permitted."""
    return int(attempt_count) < int(max_attempts)


def compute_retry_at(
    finished_at: datetime,
    retry_count: int,
    *,
    backoff_strategy: str,
    backoff_base_seconds: int,
) -> datetime:
    """Compute the next retry timestamp from policy inputs."""
    delay_seconds = compute_backoff_delay_seconds(
        backoff_strategy,
        retry_count,
        backoff_base_seconds,
    )
    return finished_at + timedelta(seconds=delay_seconds)


def compute_backoff_delay_seconds(
    backoff_strategy: str,
    retry_count: int,
    backoff_base_seconds: int,
) -> int:
    """Compute a retry delay in seconds for a given backoff strategy."""
    if retry_count <= 0:
        raise ValueError("retry_count must be >= 1.")
    if backoff_strategy not in BackoffStrategyEnum.enums:
        raise ValueError("backoff_strategy must be valid.")
    if backoff_base_seconds < 0:
        raise ValueError("backoff_base_seconds must be >= 0.")
    if backoff_strategy == "none":
        return 0
    if backoff_strategy == "fixed":
        return backoff_base_seconds
    if backoff_strategy == "exponential":
        return backoff_base_seconds * (2 ** (retry_count - 1))
    raise ValueError("Unsupported backoff_strategy.")


def _validate_policy(policy: RetryPolicy) -> None:
    """Validate retry policy settings."""
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be >= 1.")
    if policy.backoff_strategy not in BackoffStrategyEnum.enums:
        raise ValueError("backoff_strategy must be valid.")
    if policy.backoff_base_seconds < 0:
        raise ValueError("backoff_base_seconds must be >= 0.")
