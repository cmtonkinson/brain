"""Generate user-facing explanations and usage summaries."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import AttentionAuditLog

logger = logging.getLogger(__name__)


def generate_explanation(
    session: Session, signal_reference: str, *, enabled: bool = True
) -> str | None:
    """Generate a user-facing explanation for a routed notification."""
    if not enabled:
        logger.info("Explanation generation disabled.")
        return None
    record = (
        session.query(AttentionAuditLog)
        .filter(AttentionAuditLog.signal_reference == signal_reference)
        .order_by(AttentionAuditLog.timestamp.desc())
        .first()
    )
    if record is None:
        return None
    parts = [
        f"source={record.source_component}",
        f"base={record.base_assessment}",
        f"policy={record.policy_outcome or 'none'}",
        f"final={record.final_decision}",
    ]
    if record.preference_reference:
        parts.append(f"preference={record.preference_reference}")
    return "Why did I get this? " + " ".join(parts)


def generate_usage_summary(
    session: Session,
    owner: str,
    start_at: datetime,
    end_at: datetime,
    *,
    enabled: bool = True,
) -> str | None:
    """Generate an attention usage summary from audit logs."""
    if not enabled:
        logger.info("Usage summary generation disabled.")
        return None
    rows = (
        session.query(AttentionAuditLog.final_decision, func.count(AttentionAuditLog.id))
        .filter(AttentionAuditLog.timestamp >= start_at)
        .filter(AttentionAuditLog.timestamp < end_at)
        .group_by(AttentionAuditLog.final_decision)
        .all()
    )
    if not rows:
        return "No attention activity in the selected window."
    summary_parts = [f"{decision}:{count}" for decision, count in rows]
    return f"Attention summary for {owner}: " + ", ".join(summary_parts)
