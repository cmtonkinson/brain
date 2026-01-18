"""Unit tests for attention context and notification history storage."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.storage import (
    create_attention_context_window,
    get_attention_context_for_timestamp,
    get_notification_history_counts,
    record_notification_history,
)


def test_attention_context_query_returns_expected_window(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure attention context lookup returns the matching window."""
    session_factory = sqlite_session_factory
    owner = "user"
    start_at = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    end_at = datetime(2025, 1, 1, 17, 0, tzinfo=timezone.utc)
    timestamp = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        create_attention_context_window(
            session,
            owner=owner,
            source="calendar",
            start_at=start_at,
            end_at=end_at,
            interruptible=False,
        )
        session.commit()

        snapshot = get_attention_context_for_timestamp(session, owner, timestamp)

    assert snapshot.interruptible is False
    assert snapshot.window_start == start_at
    assert snapshot.window_end == end_at


def test_missing_attention_context_returns_default(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure missing attention context returns a safe default and logs a warning."""
    session_factory = sqlite_session_factory
    timestamp = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        snapshot = get_attention_context_for_timestamp(session, "user", timestamp)

    assert snapshot.interruptible is False
    assert snapshot.source == "default"
    assert any(record.levelname == "WARNING" for record in caplog.records)


def test_invalid_time_window_is_rejected(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure invalid time windows are rejected and logged."""
    session_factory = sqlite_session_factory
    start_at = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    end_at = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        with pytest.raises(ValueError):
            create_attention_context_window(
                session,
                owner="user",
                source="calendar",
                start_at=start_at,
                end_at=end_at,
                interruptible=True,
            )

    assert any(record.levelname == "ERROR" for record in caplog.records)


def test_history_query_returns_counts(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure history queries return expected counts by channel and outcome."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

    with closing(session_factory()) as session:
        record_notification_history(
            session,
            owner="user",
            signal_reference="signal-1",
            outcome="NOTIFY",
            channel="signal",
            decided_at=now - timedelta(minutes=10),
        )
        record_notification_history(
            session,
            owner="user",
            signal_reference="signal-2",
            outcome="LOG_ONLY",
            channel=None,
            decided_at=now - timedelta(minutes=5),
        )
        session.commit()

        counts = get_notification_history_counts(
            session,
            owner="user",
            start_at=now - timedelta(hours=1),
            end_at=now + timedelta(minutes=1),
        )

    outcomes = {(entry.channel, entry.outcome): entry.count for entry in counts}
    assert outcomes[(None, "LOG_ONLY")] == 1
    assert outcomes[("signal", "NOTIFY")] == 1


def test_history_query_failure_returns_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure history query failures return a safe fallback and log errors."""

    class FailingSession:
        """Session stub that raises on query to simulate failures."""

        def query(self, *args, **kwargs):
            """Raise an error to simulate query failure."""
            raise RuntimeError("boom")

    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    counts = get_notification_history_counts(
        FailingSession(),
        owner="user",
        start_at=now - timedelta(hours=1),
        end_at=now,
    )

    assert counts == []
    assert any(record.levelname == "ERROR" for record in caplog.records)
