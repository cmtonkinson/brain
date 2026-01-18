"""Preference storage and validation for attention routing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from attention.policy_schema import TimeWindow
from models import (
    AttentionAlwaysNotify,
    AttentionChannelPreference,
    AttentionDoNotDisturb,
    AttentionEscalationThreshold,
    AttentionQuietHours,
)

logger = logging.getLogger(__name__)

ALLOWED_CHANNELS = {"signal"}


class ChannelPreferenceLevel(str, Enum):
    """Allowed channel preference levels."""

    ALLOW = "allow"
    DENY = "deny"
    PREFER = "prefer"


class ChannelPreference(BaseModel):
    """Channel preference entry."""

    model_config = ConfigDict(extra="forbid")

    channel: str = Field(..., min_length=1)
    preference: ChannelPreferenceLevel

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, value: str) -> str:
        """Normalize and validate channel names."""
        normalized = value.strip()
        if normalized not in ALLOWED_CHANNELS:
            raise ValueError(f"Invalid channel preference: {normalized}")
        return normalized


class EscalationThreshold(BaseModel):
    """Escalation threshold entry."""

    model_config = ConfigDict(extra="forbid")

    signal_type: str = Field(..., min_length=1)
    threshold: int = Field(..., ge=1)

    @field_validator("signal_type")
    @classmethod
    def _strip_signal_type(cls, value: str) -> str:
        """Normalize signal type."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("signal_type must be non-empty.")
        return normalized


class AlwaysNotifyException(BaseModel):
    """Always-notify exception entry."""

    model_config = ConfigDict(extra="forbid")

    signal_type: str = Field(..., min_length=1)
    source_component: str | None = None

    @field_validator("signal_type", "source_component")
    @classmethod
    def _strip_fields(cls, value: str | None) -> str | None:
        """Normalize optional string fields."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Fields must be non-empty when provided.")
        return normalized


class AttentionPreferences(BaseModel):
    """Aggregate attention preferences for an owner."""

    model_config = ConfigDict(extra="forbid")

    quiet_hours: list[TimeWindow] = Field(default_factory=list)
    do_not_disturb: list[TimeWindow] = Field(default_factory=list)
    channel_preferences: list[ChannelPreference] = Field(default_factory=list)
    escalation_thresholds: list[EscalationThreshold] = Field(default_factory=list)
    always_notify: list[AlwaysNotifyException] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_windows(self) -> "AttentionPreferences":
        """Ensure time windows do not overlap."""
        _ensure_no_overlap(self.quiet_hours, "quiet_hours")
        _ensure_no_overlap(self.do_not_disturb, "do_not_disturb")
        return self


@dataclass(frozen=True)
class StoredPreferences:
    """Stored preferences container returned from persistence."""

    owner: str
    preferences: AttentionPreferences


def store_preferences(
    session: Session, owner: str, preferences: AttentionPreferences
) -> StoredPreferences:
    """Persist attention preferences for an owner."""
    if not owner.strip():
        raise ValueError("owner is required.")

    for window in preferences.quiet_hours:
        session.add(
            AttentionQuietHours(
                owner=owner,
                start_time=window.start,
                end_time=window.end,
                timezone=window.timezone,
            )
        )
    for window in preferences.do_not_disturb:
        session.add(
            AttentionDoNotDisturb(
                owner=owner,
                start_time=window.start,
                end_time=window.end,
                timezone=window.timezone,
            )
        )
    for pref in preferences.channel_preferences:
        session.add(
            AttentionChannelPreference(
                owner=owner,
                channel=pref.channel,
                preference=pref.preference.value,
            )
        )
    for threshold in preferences.escalation_thresholds:
        session.add(
            AttentionEscalationThreshold(
                owner=owner,
                signal_type=threshold.signal_type,
                threshold=threshold.threshold,
            )
        )
    for entry in preferences.always_notify:
        session.add(
            AttentionAlwaysNotify(
                owner=owner,
                signal_type=entry.signal_type,
                source_component=entry.source_component,
            )
        )
    session.flush()
    return StoredPreferences(owner=owner, preferences=preferences)


def load_preferences(session: Session, owner: str) -> AttentionPreferences:
    """Load stored attention preferences for an owner."""
    quiet_hours = [
        TimeWindow(start=row.start_time, end=row.end_time, timezone=row.timezone)
        for row in session.query(AttentionQuietHours).filter_by(owner=owner).all()
    ]
    do_not_disturb = [
        TimeWindow(start=row.start_time, end=row.end_time, timezone=row.timezone)
        for row in session.query(AttentionDoNotDisturb).filter_by(owner=owner).all()
    ]
    channel_preferences = [
        ChannelPreference(channel=row.channel, preference=ChannelPreferenceLevel(row.preference))
        for row in session.query(AttentionChannelPreference).filter_by(owner=owner).all()
    ]
    escalation_thresholds = [
        EscalationThreshold(signal_type=row.signal_type, threshold=row.threshold)
        for row in session.query(AttentionEscalationThreshold).filter_by(owner=owner).all()
    ]
    always_notify = [
        AlwaysNotifyException(signal_type=row.signal_type, source_component=row.source_component)
        for row in session.query(AttentionAlwaysNotify).filter_by(owner=owner).all()
    ]
    return AttentionPreferences(
        quiet_hours=quiet_hours,
        do_not_disturb=do_not_disturb,
        channel_preferences=channel_preferences,
        escalation_thresholds=escalation_thresholds,
        always_notify=always_notify,
    )


def _ensure_no_overlap(windows: list[TimeWindow], label: str) -> None:
    """Reject overlapping time windows."""
    intervals: dict[int, list[tuple[int, int]]] = {}
    for window in windows:
        for day, start, end in _expand_window(window):
            intervals.setdefault(day, []).append((start, end))
    for day, ranges in intervals.items():
        ranges.sort(key=lambda item: item[0])
        for idx in range(1, len(ranges)):
            if ranges[idx][0] < ranges[idx - 1][1]:
                logger.error("Overlapping %s windows detected on day %s.", label, day)
                raise ValueError(f"Overlapping {label} windows are not allowed.")


def _expand_window(window: TimeWindow) -> list[tuple[int, int, int]]:
    """Expand a time window into per-day minute intervals."""
    days = window.days_of_week or list(range(7))
    start_min = _time_to_minutes(window.start)
    end_min = _time_to_minutes(window.end)
    intervals: list[tuple[int, int, int]] = []
    for day in days:
        if start_min < end_min:
            intervals.append((day, start_min, end_min))
        else:
            intervals.append((day, start_min, 24 * 60))
            intervals.append(((day + 1) % 7, 0, end_min))
    return intervals


def _time_to_minutes(value: time) -> int:
    """Convert a time value into minutes since midnight."""
    return value.hour * 60 + value.minute
