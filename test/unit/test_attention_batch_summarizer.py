"""Unit tests for batch summarization and ranking."""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import sessionmaker

from attention.batch_summarizer import summarize_batch
from models import AttentionBatch, BatchedSignal


def test_batch_with_multiple_items_is_ranked(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure batches with multiple items produce a ranked list."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        batch = AttentionBatch(
            owner="user",
            batch_type="daily",
            scheduled_for=now,
        )
        session.add(batch)
        session.flush()
        session.add_all(
            [
                BatchedSignal(
                    owner="user",
                    signal_reference="signal-1",
                    source_component="scheduler",
                    topic="ops",
                    category="low",
                    batch_id=batch.id,
                ),
                BatchedSignal(
                    owner="user",
                    signal_reference="signal-2",
                    source_component="scheduler",
                    topic="ops",
                    category="low",
                    batch_id=batch.id,
                ),
            ]
        )
        session.commit()

        result = summarize_batch(session, batch.id)
        session.commit()

    assert result.decision == "DELIVER"
    assert result.summary is not None
    assert [item.rank for item in result.ranked_items] == [1, 2]


def test_batch_with_single_item_is_ranked(
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure batches with one item still produce summary and rank."""
    session_factory = sqlite_session_factory
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    with closing(session_factory()) as session:
        batch = AttentionBatch(
            owner="user",
            batch_type="daily",
            scheduled_for=now,
        )
        session.add(batch)
        session.flush()
        session.add(
            BatchedSignal(
                owner="user",
                signal_reference="signal-3",
                source_component="scheduler",
                topic="ops",
                category="low",
                batch_id=batch.id,
            )
        )
        session.commit()

        result = summarize_batch(session, batch.id)
        session.commit()

    assert result.decision == "DELIVER"
    assert result.summary is not None
    assert len(result.ranked_items) == 1
    assert result.ranked_items[0].signal_reference == "signal-3"


def test_summarization_failure_defers_delivery(
    caplog: pytest.LogCaptureFixture,
    sqlite_session_factory: sessionmaker,
) -> None:
    """Ensure summarization failures log errors and defer delivery."""
    session_factory = sqlite_session_factory
    with closing(session_factory()) as session:
        result = summarize_batch(session, 999)

    assert result.decision == "DEFER"
    assert result.error is not None
    assert any(record.levelname == "ERROR" for record in caplog.records)
