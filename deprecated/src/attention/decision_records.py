"""Persisted decision records for attention routing."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from attention.audit import AttentionAuditLogger
from models import AttentionDecisionRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DecisionRecordInput:
    """Inputs required to persist a decision record."""

    signal_reference: str
    channel: str | None
    base_assessment: str
    policy_outcome: str | None
    final_decision: str
    explanation: str


@dataclass(frozen=True)
class DecisionRecordResult:
    """Result of decision persistence."""

    decision: str
    record_id: int | None


def persist_decision_record(
    session: Session,
    record_input: DecisionRecordInput,
    audit_logger: AttentionAuditLogger | None = None,
) -> DecisionRecordResult:
    """Persist a decision record and return the resulting decision."""
    try:
        record = AttentionDecisionRecord(
            signal_reference=record_input.signal_reference,
            channel=record_input.channel,
            base_assessment=record_input.base_assessment,
            policy_outcome=record_input.policy_outcome,
            final_decision=record_input.final_decision,
            explanation=record_input.explanation,
        )
        session.add(record)
        session.flush()
        return DecisionRecordResult(decision=record.final_decision, record_id=record.id)
    except Exception:
        logger.exception("Failed to persist decision record.")
        if audit_logger:
            audit_logger.log_routing(
                source_component="attention_router",
                signal_reference=record_input.signal_reference,
                base_assessment=record_input.base_assessment,
                policy_outcome="persistence_error",
                final_decision="LOG_ONLY",
            )
        return DecisionRecordResult(decision="LOG_ONLY", record_id=None)


def get_decision_by_signal(
    session: Session, signal_reference: str
) -> AttentionDecisionRecord | None:
    """Retrieve the latest decision record for a signal reference."""
    return (
        session.query(AttentionDecisionRecord)
        .filter_by(signal_reference=signal_reference)
        .order_by(AttentionDecisionRecord.created_at.desc())
        .first()
    )
