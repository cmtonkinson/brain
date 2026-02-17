"""Services for enforcing commitment audit retention policies."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from commitments.state_transition_repository import (
    CommitmentStateTransitionRepository,
)

logger = logging.getLogger(__name__)


def enforce_transition_audit_retention(
    session_factory: Callable[[], Session],
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    """Delete commitment state transitions older than the retention window."""
    if retention_days < 0:
        raise ValueError("retention_days must be >= 0.")
    if retention_days == 0:
        return 0
    timestamp = now or datetime.now(timezone.utc)
    cutoff = timestamp - timedelta(days=retention_days)
    repository = CommitmentStateTransitionRepository(session_factory)
    deleted = repository.delete_older_than(cutoff)
    logger.info(
        "Commitment audit retention cleanup removed %s transitions older than %s days.",
        deleted,
        retention_days,
    )
    return deleted


__all__ = ["enforce_transition_audit_retention"]
