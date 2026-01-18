"""Integration tests for database migrations and persistence."""

from __future__ import annotations

from contextlib import closing
import importlib.util

import pytest
from sqlalchemy import inspect, text

from config import settings
from models import ActionLog, Conversation, IndexedChunk, IndexedNote, Task
from services import database


def _ensure_database_ready() -> None:
    """Skip tests when the integration database is not configured or reachable."""
    if not settings.database.url and not settings.database.postgres_password:
        pytest.skip("Integration DB not configured (set DATABASE_URL or POSTGRES_PASSWORD).")
    try:
        with closing(database.get_sync_engine().connect()) as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Integration DB not reachable: {exc}")


def _ensure_async_driver_ready() -> None:
    """Skip async tests when required async dependencies are missing."""
    if importlib.util.find_spec("greenlet") is None:
        pytest.skip("greenlet not installed; async SQLAlchemy tests skipped.")


def test_run_migrations_creates_tables() -> None:
    """run_migrations_sync applies migrations and creates core tables."""
    _ensure_database_ready()
    database.run_migrations_sync()

    inspector = inspect(database.get_sync_engine())
    assert inspector.has_table("action_logs") is True


def test_model_round_trip_persists_records() -> None:
    """Core models can be persisted and queried via the ORM."""
    _ensure_database_ready()
    database.run_migrations_sync()

    with closing(database.get_sync_session()) as session:
        task = Task(description="integration task", completed=False)
        conversation = Conversation(obsidian_path="Brain/Conversations/test.md")
        note = IndexedNote(
            path="Notes/Test.md",
            collection="obsidian",
            content_hash="hash",
            chunk_count=1,
        )
        session.add_all([task, conversation, note])
        session.commit()

        chunk = IndexedChunk(
            note_id=note.id,
            chunk_index=0,
            qdrant_id="qdrant-id",
            chunk_chars=10,
        )
        session.add(chunk)
        session.commit()

        fetched_task = session.get(Task, task.id)
        fetched_conversation = session.get(Conversation, conversation.id)
        fetched_note = session.get(IndexedNote, note.id)
        fetched_chunk = session.get(IndexedChunk, chunk.id)

        assert fetched_task is not None
        assert fetched_task.description == "integration task"
        assert fetched_conversation is not None
        assert fetched_conversation.obsidian_path == "Brain/Conversations/test.md"
        assert fetched_note is not None
        assert fetched_note.path == "Notes/Test.md"
        assert fetched_chunk is not None
        assert fetched_chunk.qdrant_id == "qdrant-id"

        session.delete(chunk)
        session.delete(note)
        session.delete(conversation)
        session.delete(task)
        session.commit()


@pytest.mark.asyncio
async def test_log_action_persists_record() -> None:
    """log_action persists an ActionLog record that can be queried later."""
    _ensure_database_ready()
    _ensure_async_driver_ready()
    database.run_migrations_sync()

    async with database.get_session() as session:
        action = await database.log_action(
            session,
            action_type="integration_test",
            description="inserted via integration test",
            result="ok",
        )
        action_id = action.id

    with closing(database.get_sync_session()) as sync_session:
        record = sync_session.get(ActionLog, action_id)
        assert record is not None
        assert record.action_type == "integration_test"
        assert record.description == "inserted via integration test"
        assert record.result == "ok"
        sync_session.delete(record)
        sync_session.commit()
