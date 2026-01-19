"""Fail-closed routing behavior and queueing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from attention.audit import AttentionAuditLogger
from attention.envelope_schema import RoutingEnvelope
from attention.fail_closed_storage import (
    build_fail_closed_entry,
    build_policy_tag_records,
    build_provenance_records,
    load_fail_closed_envelope,
)
from attention.router import AttentionRouter, RoutingResult
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
        envelope: RoutingEnvelope,
        *,
        router_available: bool,
        policy_available: bool,
        now: datetime | None = None,
    ) -> RoutingResult:
        """Route a signal or queue it when failing closed."""
        if not router_available or not policy_available:
            reason = "router_unavailable" if not router_available else "policy_unavailable"
            self._queue_envelope(envelope, reason, now or datetime.now(timezone.utc))
            self._audit.log_fail_closed(
                source_component=envelope.notification.source_component,
                signal_reference=envelope.signal_reference,
                base_assessment="LOG_ONLY",
                reason=reason,
            )
            return RoutingResult(decision="LOG_ONLY", channel=None)
        return await self._router.route_envelope(envelope)

    async def reprocess_queue(self, now: datetime) -> int:
        """Reprocess queued signals that are ready for retry."""
        queued = (
            self._session.query(AttentionFailClosedQueue)
            .filter(AttentionFailClosedQueue.retry_at <= now)
            .all()
        )
        processed = 0
        for entry in queued:
            envelope = load_fail_closed_envelope(self._session, entry)
            if envelope is None:
                logger.error(
                    "Dropping fail-closed entry %s due to invalid payload.",
                    entry.id,
                )
                self._session.delete(entry)
                processed += 1
                continue
            await self._router.route_envelope(envelope)
            self._session.delete(entry)
            processed += 1
        self._session.flush()
        return processed

    def _queue_envelope(self, envelope: RoutingEnvelope, reason: str, now: datetime) -> None:
        """Persist a routing envelope into the fail-closed queue."""
        entry = build_fail_closed_entry(
            envelope,
            reason=reason,
            queued_at=now,
            retry_delay=self._config.retry_delay,
        )
        self._session.add(entry)
        self._session.flush()
        self._session.add_all(build_provenance_records(entry.id, envelope.notification.provenance))
        if envelope.authorization:
            self._session.add_all(
                build_policy_tag_records(entry.id, envelope.authorization.policy_tags)
            )
