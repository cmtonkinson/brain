"""Unit tests for the ingestion index handoff helpers."""

from datetime import datetime, timezone

from ingestion.index_handoff import trigger_index_update
from models import Ingestion, IngestionIndexUpdate


def _create_ingestion(session_factory, *, now: datetime) -> Ingestion:
    with session_factory() as session:
        ingestion = Ingestion(
            source_type="test",
            source_uri="test://example",
            source_actor="author",
            created_at=now,
            status="queued",
            last_error=None,
        )
        session.add(ingestion)
        session.commit()
        session.refresh(ingestion)
        return ingestion


def test_trigger_index_update_records_success(sqlite_session_factory):
    """Successful index update dispatch should persist a success record."""
    now = datetime(2026, 2, 2, 0, 0, tzinfo=timezone.utc)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    outcome = trigger_index_update(
        ingestion.id,
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert outcome.status == "success"
    assert outcome.error is None
    with sqlite_session_factory() as session:
        rows = session.query(IngestionIndexUpdate).filter_by(ingestion_id=ingestion.id).all()
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].error is None


def test_trigger_index_update_records_failure(sqlite_session_factory):
    """A failing dispatcher records a 'failed' status with an error message."""
    now = datetime(2026, 2, 2, 0, 0, tzinfo=timezone.utc)
    ingestion = _create_ingestion(sqlite_session_factory, now=now)

    def failing_dispatcher(_: object) -> None:
        raise RuntimeError("dispatch failed")

    outcome = trigger_index_update(
        ingestion.id,
        dispatcher=failing_dispatcher,
        session_factory=sqlite_session_factory,
        now=now,
    )

    assert outcome.status == "failed"
    assert outcome.error == "dispatch failed"
    with sqlite_session_factory() as session:
        rows = session.query(IngestionIndexUpdate).filter_by(ingestion_id=ingestion.id).all()
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert "dispatch failed" in rows[0].error
