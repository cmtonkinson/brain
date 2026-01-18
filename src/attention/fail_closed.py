"""Fail-closed routing behavior and queueing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from attention.audit import AttentionAuditLogger
from attention.router import AttentionRouter, OutboundSignal, RoutingResult
from models import AttentionFailClosedQueue

logger = logging.getLogger(__name__)

DEFAULT_RETRY_DELAY = timedelta(minutes=15)


@dataclass(frozen=True)
class FailClosedConfig:
    """Configuration for fail-closed behavior."""

    retry_delay: timedelta = DEFAULT_RETRY_DELAY


class FailClosedRouter:
    """Fail-closed wrapper around the attention router."""

    def __init__(
        self,
        router: AttentionRouter,
        session: Session,
        audit_logger: AttentionAuditLogger,
        config: FailClosedConfig | None = None,
    ) -> None:
        """Initialize the fail-closed router."""
        self._router = router
        self._session = session
        self._audit = audit_logger
        self._config = config or FailClosedConfig()

    async def route(
        self,
        signal: OutboundSignal,
        *,
        router_available: bool,
        policy_available: bool,
        now: datetime | None = None,
    ) -> RoutingResult:
        """Route a signal or queue it when failing closed."""
        if not router_available or not policy_available:
            reason = "router_unavailable" if not router_available else "policy_unavailable"
            self._queue_signal(signal, reason, now or datetime.now(timezone.utc))
            self._audit.log_fail_closed(
                source_component=signal.source_component,
                signal_reference=signal.message[:50],
                base_assessment="LOG_ONLY",
                reason=reason,
            )
            return RoutingResult(decision="LOG_ONLY", channel=None)
        return await self._router.route_signal(signal)

    async def reprocess_queue(self, now: datetime) -> int:
        """Reprocess queued signals that are ready for retry."""
        queued = (
            self._session.query(AttentionFailClosedQueue)
            .filter(AttentionFailClosedQueue.retry_at <= now)
            .all()
        )
        processed = 0
        for entry in queued:
            signal = OutboundSignal(
                source_component=entry.source_component,
                channel=entry.channel,
                from_number=entry.from_number,
                to_number=entry.to_number,
                message=entry.message,
            )
            await self._router.route_signal(signal)
            self._session.delete(entry)
            processed += 1
        self._session.flush()
        return processed

    def _queue_signal(self, signal: OutboundSignal, reason: str, now: datetime) -> None:
        """Persist a signal into the fail-closed queue."""
        entry = AttentionFailClosedQueue(
            owner=signal.to_number,
            source_component=signal.source_component,
            from_number=signal.from_number,
            to_number=signal.to_number,
            channel=signal.channel,
            message=signal.message,
            reason=reason,
            queued_at=now,
            retry_at=now + self._config.retry_delay,
        )
        self._session.add(entry)
        self._session.flush()
