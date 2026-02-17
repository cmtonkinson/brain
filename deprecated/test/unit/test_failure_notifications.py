"""Unit tests for scheduled execution failure notifications."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from attention.envelope_schema import RoutingEnvelope
from config import settings
from models import NotificationHistoryEntry
from scheduler import data_access
from scheduler.failure_notifications import FailureNotificationConfig, FailureNotificationService


class _FakeRouter:
    """Stub attention router that records routed envelopes."""

    def __init__(self) -> None:
        """Initialize the router with an empty route log."""
        self.routed: list[RoutingEnvelope] = []

    async def route_envelope(self, envelope: RoutingEnvelope) -> None:
        """Record the routed envelope."""
        self.routed.append(envelope)


def _seed_failed_execution(session, *, failure_count: int) -> tuple[int, int]:
    """Create a schedule/execution pair with the requested failure count."""
    actor = data_access.ActorContext(
        actor_type="human",
        actor_id="tester",
        channel="cli",
        trace_id="trace-seed",
        request_id="req-seed",
    )
    intent, schedule = data_access.create_schedule_with_intent(
        session,
        data_access.ScheduleCreateWithIntentInput(
            task_intent=data_access.TaskIntentInput(summary="Failure schedule"),
            schedule_type="interval",
            timezone="UTC",
            definition=data_access.ScheduleDefinitionInput(interval_count=1, interval_unit="day"),
        ),
        actor,
    )
    execution_actor = data_access.ExecutionActorContext(
        actor_type="scheduled",
        actor_id=None,
        channel="scheduler",
        trace_id="trace-exec",
        request_id="req-exec",
        actor_context="scheduled_failure",
    )
    execution = data_access.create_execution(
        session,
        data_access.ExecutionCreateInput(
            task_intent_id=intent.id,
            schedule_id=schedule.id,
            scheduled_for=datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc),
            status="failed",
            failure_count=failure_count,
            last_error_code="boom",
            last_error_message="Failure detail",
        ),
        execution_actor,
        now=datetime(2025, 2, 1, 10, 5, tzinfo=timezone.utc),
    )
    update_actor = data_access.ActorContext(
        actor_type="system",
        actor_id=None,
        channel="scheduler",
        trace_id="trace-update",
        request_id="req-update",
    )
    data_access.update_schedule(
        session,
        schedule.id,
        data_access.ScheduleUpdateInput(failure_count=failure_count),
        update_actor,
        now=datetime(2025, 2, 1, 10, 6, tzinfo=timezone.utc),
    )
    return schedule.id, execution.id


def test_failure_notification_skips_below_threshold(sqlite_session_factory) -> None:
    """Ensure failure notifications are skipped until the threshold is reached."""
    now = datetime(2025, 2, 1, 11, 0, tzinfo=timezone.utc)
    router = _FakeRouter()
    service = FailureNotificationService(
        sqlite_session_factory,
        router,
        config=FailureNotificationConfig(threshold=2, throttle_window_seconds=3600),
        now_provider=lambda: now,
    )

    with closing(sqlite_session_factory()) as session:
        _, execution_id = _seed_failed_execution(session, failure_count=1)
        session.commit()

    assert service.notify_if_needed(execution_id) is False
    assert router.routed == []


def test_failure_notification_throttles_repeat_alerts(sqlite_session_factory) -> None:
    """Ensure failure notifications throttle repeated alerts within the window."""
    now = datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc)
    router = _FakeRouter()
    service = FailureNotificationService(
        sqlite_session_factory,
        router,
        config=FailureNotificationConfig(threshold=2, throttle_window_seconds=3600),
        now_provider=lambda: now,
    )

    with closing(sqlite_session_factory()) as session:
        schedule_id, execution_id = _seed_failed_execution(session, failure_count=2)
        session.commit()

    assert service.notify_if_needed(execution_id) is True
    assert len(router.routed) == 1

    with closing(sqlite_session_factory()) as session:
        session.add(
            NotificationHistoryEntry(
                owner=settings.signal.allowed_senders[0],
                signal_reference=f"schedule.failure:{schedule_id}",
                outcome="LOG_ONLY",
                channel=None,
                created_at=now - timedelta(minutes=5),
            )
        )
        session.commit()

    assert service.notify_if_needed(execution_id) is False
    assert len(router.routed) == 1
