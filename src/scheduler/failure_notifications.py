"""Failure notification throttling for scheduled executions."""

from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from attention.envelope_schema import RoutingEnvelope
from attention.router import AttentionRouter
from attention.routing_envelope import build_schedule_failure_envelope
from config import settings
from models import Execution, NotificationHistoryEntry, Schedule, TaskIntent
from scheduler.actor_context import ScheduledActorContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailureNotificationConfig:
    """Configuration for scheduled execution failure notifications."""

    threshold: int
    throttle_window_seconds: int
    source_component: str = "scheduler_dispatcher"
    urgency: float = 0.7
    channel_cost: float = 0.3


def resolve_failure_notification_config(
    config: FailureNotificationConfig | None,
) -> FailureNotificationConfig:
    """Resolve failure notification configuration with defaults."""
    if config is not None:
        _validate_config(config)
        return config
    scheduler_config = settings.scheduler
    resolved = FailureNotificationConfig(
        threshold=int(scheduler_config.failure_notification_threshold),
        throttle_window_seconds=int(scheduler_config.failure_notification_throttle_seconds),
    )
    _validate_config(resolved)
    return resolved


class FailureNotificationService:
    """Routes attention notifications for repeated scheduled execution failures."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        router: AttentionRouter,
        *,
        config: FailureNotificationConfig | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize with persistence, routing, and configuration dependencies."""
        self._session_factory = session_factory
        self._router = router
        self._config = resolve_failure_notification_config(config)
        self._now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def notify_if_needed(self, execution_id: int) -> bool:
        """Route a failure notification when threshold and throttle allow."""
        now = self._now_provider()
        with closing(self._session_factory()) as session:
            execution = session.query(Execution).filter(Execution.id == execution_id).first()
            if execution is None:
                logger.error("Failure notification skipped: execution %s not found.", execution_id)
                return False
            schedule = session.query(Schedule).filter(Schedule.id == execution.schedule_id).first()
            if schedule is None:
                logger.error(
                    "Failure notification skipped: schedule %s not found.",
                    execution.schedule_id,
                )
                return False
            intent = session.query(TaskIntent).filter(TaskIntent.id == schedule.task_intent_id).first()
            if intent is None:
                logger.error(
                    "Failure notification skipped: intent %s not found.",
                    schedule.task_intent_id,
                )
                return False

            failure_count = int(schedule.failure_count or 0)
            if failure_count < self._config.threshold:
                return False

            owner = _resolve_default_owner()
            if owner is None:
                logger.error("Failure notification skipped: no default owner configured.")
                return False

            signal_reference = f"schedule.failure:{schedule.id}"
            if _is_throttled(
                session,
                owner=owner,
                signal_reference=signal_reference,
                now=now,
                throttle_window_seconds=self._config.throttle_window_seconds,
            ):
                return False

            envelope = build_schedule_failure_envelope(
                owner=owner,
                schedule_id=schedule.id,
                execution_id=execution.id,
                task_summary=intent.summary,
                failure_count=failure_count,
                failure_threshold=self._config.threshold,
                throttle_window_seconds=self._config.throttle_window_seconds,
                last_error_code=execution.last_error_code,
                last_error_message=execution.last_error_message,
                source_component=self._config.source_component,
                urgency=self._config.urgency,
                channel_cost=self._config.channel_cost,
                trace_id=execution.trace_id,
                timestamp=now,
                actor_context=ScheduledActorContext(),
            )

        _route_failure_notification(self._router, envelope)
        return True


def _route_failure_notification(router: AttentionRouter, envelope: RoutingEnvelope) -> None:
    """Route a failure notification through the attention router."""
    try:
        asyncio.run(router.route_envelope(envelope))
    except RuntimeError as exc:
        logger.exception("Failed to route failure notification: %s", exc)
    except Exception:
        logger.exception("Failure notification routing failed unexpectedly.")


def _is_throttled(
    session: Session,
    *,
    owner: str,
    signal_reference: str,
    now: datetime,
    throttle_window_seconds: int,
) -> bool:
    """Return True when a recent notification exists within the throttle window."""
    if throttle_window_seconds <= 0:
        return False
    window_start = now - timedelta(seconds=throttle_window_seconds)
    window_start = _normalize_window_start(session, window_start)
    base_query = (
        session.query(NotificationHistoryEntry)
        .filter(NotificationHistoryEntry.signal_reference == signal_reference)
        .filter(NotificationHistoryEntry.created_at >= window_start)
        .order_by(NotificationHistoryEntry.created_at.desc())
    )
    existing = base_query.filter(NotificationHistoryEntry.owner == owner).first()
    if existing is None:
        existing = base_query.first()
    return existing is not None


def _resolve_default_owner() -> str | None:
    """Return the default notification owner from Signal allowlists."""
    allowlist = settings.signal.allowed_senders_by_channel.get("signal")
    if allowlist:
        return allowlist[0]
    if settings.signal.allowed_senders:
        return settings.signal.allowed_senders[0]
    return None


def _normalize_window_start(session: Session, window_start: datetime) -> datetime:
    """Normalize throttle timestamps for storage backends."""
    if session.bind and session.bind.dialect.name == "sqlite" and window_start.tzinfo is not None:
        return window_start.replace(tzinfo=None)
    return window_start


def _validate_config(config: FailureNotificationConfig) -> None:
    """Validate failure notification settings."""
    if config.threshold < 1:
        raise ValueError("failure notification threshold must be >= 1.")
    if config.throttle_window_seconds < 0:
        raise ValueError("failure notification throttle window must be >= 0.")
