"""Unit tests for database session helpers."""

from __future__ import annotations

from datetime import datetime

import pytest

from models import ActionLog
from services import database


class FakeAsyncSession:
    """Async session stub capturing commits and rollbacks."""

    def __init__(self) -> None:
        """Initialize call tracking."""
        self.committed = False
        self.rolled_back = False
        self.added: list[ActionLog] = []
        self.flushed = False

    async def __aenter__(self) -> "FakeAsyncSession":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Exit the async context manager."""
        return False

    async def commit(self) -> None:
        """Mark commit as called."""
        self.committed = True

    async def rollback(self) -> None:
        """Mark rollback as called."""
        self.rolled_back = True

    def add(self, item: ActionLog) -> None:
        """Record added models."""
        self.added.append(item)

    async def flush(self) -> None:
        """Mark flush as called."""
        self.flushed = True


@pytest.mark.asyncio
async def test_get_session_commits_on_success(monkeypatch) -> None:
    """get_session commits after successful usage."""
    session = FakeAsyncSession()
    monkeypatch.setattr(database, "async_session_factory", lambda: session)

    async with database.get_session() as active_session:
        assert active_session is session

    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_get_session_rolls_back_on_error(monkeypatch) -> None:
    """get_session rolls back when an exception is raised."""
    session = FakeAsyncSession()
    monkeypatch.setattr(database, "async_session_factory", lambda: session)

    with pytest.raises(RuntimeError, match="boom"):
        async with database.get_session():
            raise RuntimeError("boom")

    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_log_action_adds_and_flushes() -> None:
    """log_action adds an ActionLog and flushes the session."""
    session = FakeAsyncSession()

    action = await database.log_action(
        session,
        action_type="search",
        description="searched notes",
        result="ok",
    )

    assert session.flushed is True
    assert session.added == [action]
    assert action.action_type == "search"
    assert action.description == "searched notes"
    assert action.result == "ok"
    assert isinstance(action.timestamp, datetime)
