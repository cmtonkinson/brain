"""Delivery helpers for daily batch reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from attention.router import AttentionRouter, RoutingResult
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    submit_commitment_notification,
)
from models import Commitment
from time_utils import to_utc

logger = logging.getLogger(__name__)


def deliver_batch_reminder(
    router: AttentionRouter,
    *,
    commitments: Iterable[Commitment],
    message: str,
    owner: str | None = None,
    now: datetime | None = None,
) -> RoutingResult | None:
    """Deliver a batch reminder message via the attention router."""
    commitment_list = list(commitments)
    if not commitment_list:
        logger.info("Batch reminder skipped: no commitments due.")
        return None
    if not message.strip():
        logger.info("Batch reminder skipped: empty message.")
        return None
    timestamp = to_utc(now or datetime.now(timezone.utc))
    commitment_id = min(item.commitment_id for item in commitment_list)
    notification = CommitmentNotification(
        commitment_id=commitment_id,
        notification_type=CommitmentNotificationType.BATCH,
        message=message,
        urgency=None,
        channel="signal",
    )
    commitment_ids = [item.commitment_id for item in commitment_list]
    logger.info(
        "Batch reminder delivery submitted: commitment_ids=%s timestamp=%s",
        commitment_ids,
        timestamp.isoformat(),
    )
    result = submit_commitment_notification(
        router,
        notification,
        owner=owner,
        now=timestamp,
    )
    logger.info(
        "Batch reminder delivery result: commitment_ids=%s decision=%s timestamp=%s",
        commitment_ids,
        result.decision,
        timestamp.isoformat(),
    )
    return result


__all__ = [
    "deliver_batch_reminder",
]
