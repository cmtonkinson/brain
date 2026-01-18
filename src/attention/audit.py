"""Audit logging for attention routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy.orm import Session

from models import AttentionAuditLog

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Allowed attention audit event types."""

    SIGNAL = "SIGNAL"
    BASE_ASSESSMENT = "BASE_ASSESSMENT"
    ROUTING = "ROUTING"
    PREFERENCE = "PREFERENCE"
    RATE_LIMIT = "RATE_LIMIT"
    NOTIFICATION = "NOTIFICATION"
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class AuditLogRequest:
    """Inputs for a single attention audit log entry."""

    event_type: AuditEventType
    source_component: str
    signal_reference: str
    base_assessment: str
    policy_outcome: str | None
    final_decision: str
    envelope_id: int | None = None
    timestamp: datetime | None = None
    preference_reference: str | None = None


class AttentionAuditLogger:
    """Write attention audit entries with failure isolation."""

    def __init__(self, session: Session) -> None:
        """Initialize the audit logger with a database session."""
        self._session = session

    def log(self, request: AuditLogRequest) -> bool:
        """Persist a new audit log entry and return success status."""
        try:
            entry = AttentionAuditLog(
                event_type=request.event_type.value,
                source_component=request.source_component.strip(),
                signal_reference=request.signal_reference.strip(),
                base_assessment=request.base_assessment.strip(),
                policy_outcome=request.policy_outcome.strip() if request.policy_outcome else None,
                final_decision=request.final_decision.strip(),
                envelope_id=request.envelope_id,
                preference_reference=(
                    request.preference_reference.strip() if request.preference_reference else None
                ),
                timestamp=request.timestamp or datetime.now(timezone.utc),
            )
            self._session.add(entry)
            self._session.flush()
        except Exception:
            logger.exception("Attention audit logging failed.")
            return False
        return True

    def log_signal(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        policy_outcome: str | None,
        final_decision: str,
    ) -> bool:
        """Log a signal event with routing metadata."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.SIGNAL,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=policy_outcome,
                final_decision=final_decision,
            )
        )

    def log_routing(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        policy_outcome: str | None,
        final_decision: str,
    ) -> bool:
        """Log a routing decision event with policy metadata."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.ROUTING,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=policy_outcome,
                final_decision=final_decision,
            )
        )

    def log_base_assessment(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
    ) -> bool:
        """Log a base assessment before policy application."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.BASE_ASSESSMENT,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=None,
                final_decision=base_assessment,
            )
        )

    def log_notification(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        policy_outcome: str | None,
        final_decision: str,
        envelope_id: int,
    ) -> bool:
        """Log a notification event linked to a notification envelope."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.NOTIFICATION,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=policy_outcome,
                final_decision=final_decision,
                envelope_id=envelope_id,
            )
        )

    def log_preference_application(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        final_decision: str,
        preference_reference: str,
    ) -> bool:
        """Log a preference application event with reference metadata."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.PREFERENCE,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=None,
                final_decision=final_decision,
                preference_reference=preference_reference,
            )
        )

    def log_rate_limit(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        final_decision: str,
        reason: str,
    ) -> bool:
        """Log a rate limit decision event."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.RATE_LIMIT,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=reason,
                final_decision=final_decision,
            )
        )

    def log_fail_closed(
        self,
        source_component: str,
        signal_reference: str,
        base_assessment: str,
        reason: str,
    ) -> bool:
        """Log a fail-closed routing event."""
        return self.log(
            AuditLogRequest(
                event_type=AuditEventType.FAIL_CLOSED,
                source_component=source_component,
                signal_reference=signal_reference,
                base_assessment=base_assessment,
                policy_outcome=reason,
                final_decision="LOG_ONLY",
            )
        )
