"""Unit tests for commitment notification routing helpers."""

from __future__ import annotations

import logging

from attention.router import RoutingResult
from commitments.notifications import (
    CommitmentNotification,
    CommitmentNotificationType,
    normalize_urgency_priority,
    submit_commitment_notification,
)


class _RouterStub:
    """Test stub for the attention router."""

    def __init__(self, result: RoutingResult) -> None:
        self._result = result
        self.envelopes = []

    async def route_envelope(self, envelope):
        """Return a preset routing result and capture envelopes."""
        self.envelopes.append(envelope)
        return self._result


def test_urgency_mapping_defaults_and_clamps() -> None:
    """Urgency values should normalize into the expected priority range."""
    assert normalize_urgency_priority(95) == 0.95
    assert normalize_urgency_priority(25) == 0.25
    assert normalize_urgency_priority(None) == 0.5


def test_submission_logs_and_sets_channel(caplog) -> None:
    """Routing submissions should log and set the signal channel."""
    result = RoutingResult(decision="NOTIFY:signal", channel="signal")
    router = _RouterStub(result)
    notification = CommitmentNotification(
        commitment_id=42,
        notification_type=CommitmentNotificationType.MISSED,
        message="Missed commitment.",
        urgency=95,
    )

    caplog.set_level(logging.INFO)

    returned = submit_commitment_notification(router, notification, owner="user")

    assert returned == result
    assert router.envelopes[0].channel_hint == "signal"
    assert "commitment_id=42" in caplog.text
    assert "notification_type=MISSED" in caplog.text


def test_router_rejection_logged_without_raising(caplog) -> None:
    """Router rejections should be logged without raising exceptions."""
    result = RoutingResult(decision="LOG_ONLY", channel=None, error="rejected")
    router = _RouterStub(result)
    notification = CommitmentNotification(
        commitment_id=99,
        notification_type=CommitmentNotificationType.REMINDER,
        message="Reminder",
        urgency=None,
    )

    caplog.set_level(logging.WARNING)

    returned = submit_commitment_notification(router, notification, owner="user")

    assert returned == result
    assert "rejected" in caplog.text
