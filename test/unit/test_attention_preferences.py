"""Unit tests for attention preference storage and validation."""

from __future__ import annotations

from contextlib import closing
from datetime import time

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker

from attention.preferences import (
    AlwaysNotifyException,
    AttentionPreferences,
    ChannelPreference,
    ChannelPreferenceLevel,
    EscalationThreshold,
    load_preferences,
    store_preferences,
)
from attention.policy_schema import TimeWindow


def test_preference_set_stores_and_loads(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure valid preference sets are persisted and retrievable."""
    session_factory = sqlite_session_factory
    preferences = AttentionPreferences(
        quiet_hours=[TimeWindow(start=time(22, 0), end=time(6, 0), timezone="UTC")],
        do_not_disturb=[TimeWindow(start=time(12, 0), end=time(13, 0), timezone="UTC")],
        channel_preferences=[
            ChannelPreference(channel="signal", preference=ChannelPreferenceLevel.PREFER)
        ],
        escalation_thresholds=[EscalationThreshold(signal_type="task.failed", threshold=2)],
        always_notify=[AlwaysNotifyException(signal_type="task.failed")],
    )

    with closing(session_factory()) as session:
        stored = store_preferences(session, "user", preferences)
        session.commit()

        loaded = load_preferences(session, "user")

    assert stored.owner == "user"
    assert len(loaded.quiet_hours) == 1
    assert len(loaded.do_not_disturb) == 1
    assert len(loaded.channel_preferences) == 1
    assert len(loaded.escalation_thresholds) == 1
    assert len(loaded.always_notify) == 1


def test_overlapping_time_windows_are_rejected() -> None:
    """Ensure overlapping time windows are rejected."""
    with pytest.raises(ValueError):
        AttentionPreferences(
            quiet_hours=[
                TimeWindow(start=time(21, 0), end=time(23, 0), timezone="UTC"),
                TimeWindow(start=time(22, 30), end=time(23, 30), timezone="UTC"),
            ]
        )


def test_invalid_channel_preference_is_rejected() -> None:
    """Ensure invalid channel preferences are rejected."""
    with pytest.raises(ValidationError):
        AttentionPreferences(
            channel_preferences=[
                ChannelPreference(channel="fax", preference=ChannelPreferenceLevel.ALLOW)
            ]
        )
