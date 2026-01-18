"""Unit tests for attention rate limiting."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.rate_limiter import RateLimitConfig, RateLimitInput, evaluate_rate_limit
from models import NotificationHistoryEntry


def test_within_rate_limit_allows_notification(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure notifications within limits are allowed."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        session.add(
            NotificationHistoryEntry(
                owner="user",
                signal_reference="signal-1",
                outcome="NOTIFY:signal",
                channel="signal",
                created_at=now - timedelta(minutes=1),
            )
        )
        session.commit()

        decision = evaluate_rate_limit(
            session,
            RateLimitInput(
                owner="user",
                signal_reference="signal-2",
                source_component="scheduler",
                channel="signal",
                channel_cost=0.2,
                timestamp=now,
                base_assessment="NOTIFY",
            ),
            RateLimitConfig(channel="signal", max_per_window=2, window_seconds=600),
        )

    assert decision.allowed is True
    assert decision.decision == "ALLOW"


def test_exceeding_rate_limit_defers_or_batches(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure exceeding limits results in deferral or batching."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        for idx in range(3):
            session.add(
                NotificationHistoryEntry(
                    owner="user",
                    signal_reference=f"signal-{idx}",
                    outcome="NOTIFY:signal",
                    channel="signal",
                    created_at=now - timedelta(minutes=idx),
                )
            )
        session.commit()

        decision = evaluate_rate_limit(
            session,
            RateLimitInput(
                owner="user",
                signal_reference="signal-4",
                source_component="scheduler",
                channel="signal",
                channel_cost=0.9,
                timestamp=now,
                base_assessment="NOTIFY",
            ),
            RateLimitConfig(channel="signal", max_per_window=2, window_seconds=600),
        )

    assert decision.allowed is False
    assert decision.decision in {"DEFER", "BATCH"}


def test_invalid_rate_limit_falls_back_to_log_only(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure invalid rate limits fall back to LOG_ONLY."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        decision = evaluate_rate_limit(
            session,
            RateLimitInput(
                owner="user",
                signal_reference="signal-5",
                source_component="scheduler",
                channel="signal",
                channel_cost=0.2,
                timestamp=now,
                base_assessment="NOTIFY",
            ),
            RateLimitConfig(channel="signal", max_per_window=0, window_seconds=0),
        )

    assert decision.allowed is False
    assert decision.decision == "LOG_ONLY"
    assert any(record.levelname == "ERROR" for record in caplog.records)
