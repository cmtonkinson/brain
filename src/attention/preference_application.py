"""Apply attention preferences and overrides to routing decisions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from attention.assessment_engine import BaseAssessmentOutcome, LOW_URGENCY
from attention.audit import AttentionAuditLogger
from models import (
    AttentionAlwaysNotify,
    AttentionChannelPreference,
    AttentionDoNotDisturb,
    AttentionQuietHours,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreferenceApplicationInputs:
    """Inputs for applying attention preferences."""

    owner: str
    signal_reference: str
    source_component: str
    urgency_score: float
    channel: str
    timestamp: datetime


@dataclass(frozen=True)
class PreferenceApplicationResult:
    """Result of applying preferences to a routing decision."""

    final_decision: str
    explanation: str
    preference_reference: str | None


def resolve_preference_flags(
    session: Session,
    owner: str,
    timestamp: datetime,
) -> dict[str, bool]:
    """Resolve preference flags for policy input evaluation."""
    quiet_hours = session.query(AttentionQuietHours).filter_by(owner=owner).all()
    dnd_windows = session.query(AttentionDoNotDisturb).filter_by(owner=owner).all()
    quiet_match = _match_time_window(quiet_hours, timestamp)
    dnd_match = _match_time_window(dnd_windows, timestamp)
    return {
        "quiet_hours": bool(quiet_match),
        "do_not_disturb": bool(dnd_match),
    }


def apply_preferences(
    session: Session,
    inputs: PreferenceApplicationInputs,
    base_assessment: BaseAssessmentOutcome,
    audit_logger: AttentionAuditLogger | None = None,
) -> PreferenceApplicationResult:
    """Apply stored preferences to the base assessment outcome."""
    quiet_hours = session.query(AttentionQuietHours).filter_by(owner=inputs.owner).all()
    dnd_windows = session.query(AttentionDoNotDisturb).filter_by(owner=inputs.owner).all()
    channel_prefs = session.query(AttentionChannelPreference).filter_by(owner=inputs.owner).all()
    always_notify = session.query(AttentionAlwaysNotify).filter_by(owner=inputs.owner).all()

    if not (quiet_hours or dnd_windows or channel_prefs or always_notify):
        logger.warning("No preferences found for owner=%s.", inputs.owner)
        return PreferenceApplicationResult(
            final_decision=_format_base_decision(base_assessment, inputs.channel),
            explanation="no_preferences",
            preference_reference=None,
        )

    preferred_channel = _preferred_channel(channel_prefs)
    preferred_channel_name = preferred_channel[0] if preferred_channel else None
    preferred_channel_id = preferred_channel[1] if preferred_channel else None
    always_notify_match = _match_always_notify(always_notify, inputs)

    if always_notify_match:
        final_decision = _format_base_decision(
            BaseAssessmentOutcome.NOTIFY, preferred_channel_name or inputs.channel
        )
        preference_reference = f"always_notify:{always_notify_match.id}"
        return _record_preference(
            inputs,
            base_assessment,
            final_decision,
            preference_reference,
            audit_logger,
        )

    dnd_match = _match_time_window(dnd_windows, inputs.timestamp)
    if dnd_match:
        final_decision = BaseAssessmentOutcome.DEFER.value
        preference_reference = f"do_not_disturb:{dnd_match.id}"
        return _record_preference(
            inputs,
            base_assessment,
            final_decision,
            preference_reference,
            audit_logger,
        )

    quiet_match = _match_time_window(quiet_hours, inputs.timestamp)
    if quiet_match and inputs.urgency_score <= LOW_URGENCY:
        final_decision = BaseAssessmentOutcome.DEFER.value
        preference_reference = f"quiet_hours:{quiet_match.id}"
        return _record_preference(
            inputs,
            base_assessment,
            final_decision,
            preference_reference,
            audit_logger,
        )

    if preferred_channel_name and base_assessment == BaseAssessmentOutcome.NOTIFY:
        final_decision = _format_base_decision(base_assessment, preferred_channel_name)
        preference_reference = f"channel_preference:{preferred_channel_id}"
        return _record_preference(
            inputs,
            base_assessment,
            final_decision,
            preference_reference,
            audit_logger,
        )

    return PreferenceApplicationResult(
        final_decision=_format_base_decision(base_assessment, inputs.channel),
        explanation="no_preference_applied",
        preference_reference=None,
    )


def _record_preference(
    inputs: PreferenceApplicationInputs,
    base_assessment: BaseAssessmentOutcome,
    final_decision: str,
    preference_reference: str,
    audit_logger: AttentionAuditLogger | None,
) -> PreferenceApplicationResult:
    """Build a preference application result and audit it."""
    explanation = f"preference_applied:{preference_reference}"
    if audit_logger:
        audit_logger.log_preference_application(
            source_component=inputs.source_component,
            signal_reference=inputs.signal_reference,
            base_assessment=base_assessment.value,
            final_decision=final_decision,
            preference_reference=preference_reference,
        )
    return PreferenceApplicationResult(
        final_decision=final_decision,
        explanation=explanation,
        preference_reference=preference_reference,
    )


def _format_base_decision(base: BaseAssessmentOutcome, channel: str) -> str:
    """Format a base assessment into a decision string."""
    if base == BaseAssessmentOutcome.NOTIFY:
        return f"NOTIFY:{channel}"
    return base.value


def _preferred_channel(
    preferences: Iterable[AttentionChannelPreference],
) -> tuple[str, int] | None:
    """Return the preferred channel and its record id, if any."""
    for pref in preferences:
        if pref.preference == "prefer":
            return pref.channel, pref.id
    return None


def _match_always_notify(
    records: Iterable[AttentionAlwaysNotify],
    inputs: PreferenceApplicationInputs,
) -> AttentionAlwaysNotify | None:
    """Return the first always-notify match for the inputs."""
    for record in records:
        if record.signal_type != inputs.signal_reference:
            continue
        if record.source_component and record.source_component != inputs.source_component:
            continue
        return record
    return None


def _match_time_window(
    records: Iterable[AttentionQuietHours] | Iterable[AttentionDoNotDisturb],
    timestamp: datetime,
):
    """Return the first time window record that matches the timestamp."""
    if timestamp.tzinfo is None:
        logger.warning("Naive timestamp provided for preference matching; assuming UTC.")
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    for record in records:
        candidate = timestamp
        if record.timezone:
            try:
                candidate = timestamp.astimezone(ZoneInfo(record.timezone))
            except Exception:
                logger.error("Invalid timezone for preference window: %s", record.timezone)
                continue
        if _time_in_window(candidate, record.start_time, record.end_time):
            return record
    return None


def _time_in_window(timestamp: datetime, start, end) -> bool:
    """Return True when a timestamp's time falls within the window."""
    current = timestamp.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end
