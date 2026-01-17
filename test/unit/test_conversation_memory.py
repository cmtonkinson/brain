"""Unit tests for conversation memory persistence."""

from __future__ import annotations

from datetime import datetime

import pytest

from config import settings
from tools.memory import ConversationMemory, get_conversation_path


class FakeObsidianClient:
    """Minimal async Obsidian client for ConversationMemory tests."""

    def __init__(self) -> None:
        """Initialize in-memory note storage."""
        self.notes: dict[str, str] = {}
        self.created_paths: list[str] = []
        self.append_calls: list[tuple[str, str]] = []

    async def note_exists(self, path: str) -> bool:
        """Return True if a note exists in memory."""
        return path in self.notes

    async def create_note(self, path: str, content: str) -> dict[str, str]:
        """Create a new note in memory."""
        self.notes[path] = content
        self.created_paths.append(path)
        return {"path": path}

    async def append_to_note(self, path: str, content: str) -> dict[str, str]:
        """Append content to a note in memory."""
        existing = self.notes.get(path, "")
        self.notes[path] = f"{existing}{content}"
        self.append_calls.append((path, content))
        return {"path": path}

    async def get_note(self, path: str) -> str:
        """Return note content or raise FileNotFoundError."""
        if path not in self.notes:
            raise FileNotFoundError(path)
        return self.notes[path]


@pytest.mark.asyncio
async def test_get_or_create_conversation_reuses_cache(monkeypatch) -> None:
    """get_or_create_conversation reuses cached paths for same day."""
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)
    timestamp = datetime(2026, 1, 12, 9, 0, 0)

    path1 = await memory.get_or_create_conversation("sender", timestamp, channel="signal")
    path2 = await memory.get_or_create_conversation("sender", timestamp, channel="signal")

    assert path1 == path2
    assert obsidian.created_paths == [path1]


@pytest.mark.asyncio
async def test_log_message_appends_markdown(monkeypatch) -> None:
    """log_message appends formatted markdown content to the note."""
    monkeypatch.setattr(settings.user, "name", "Tester", raising=False)
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)
    timestamp = datetime(2026, 1, 12, 10, 30, 0)

    await memory.log_message("sender", "user", "hello", timestamp, channel="signal")

    path = get_conversation_path(timestamp, "sender", channel="signal")
    assert "## 10:30 - Tester" in obsidian.notes[path]
    assert "hello" in obsidian.notes[path]


@pytest.mark.asyncio
async def test_get_recent_context_truncates_at_boundary(monkeypatch) -> None:
    """get_recent_context trims to max_chars and aligns to message boundary."""
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)
    timestamp = datetime.now()
    path = get_conversation_path(timestamp, "sender", channel="signal")
    content = "\n".join(
        [
            "Header",
            "## 09:00 - User",
            "First message",
            "## 09:01 - Brain",
            "Second message",
        ]
    )
    obsidian.notes[path] = content

    boundary_segment = "\n## 09:01 - Brain\nSecond message"
    max_chars = len(boundary_segment) + 2
    result = await memory.get_recent_context("sender", max_chars=max_chars, channel="signal")

    assert result is not None
    assert result.lstrip().startswith("## 09:01 - Brain")


@pytest.mark.asyncio
async def test_get_recent_context_missing_note_returns_none(monkeypatch) -> None:
    """get_recent_context returns None when the note is missing."""
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)

    result = await memory.get_recent_context("sender", max_chars=50, channel="signal")

    assert result is None


def test_should_write_summary_interval() -> None:
    """should_write_summary returns True on the configured interval."""
    obsidian = FakeObsidianClient()
    memory = ConversationMemory(obsidian)

    assert memory.should_write_summary("sender", interval=2, channel="signal") is False
    assert memory.should_write_summary("sender", interval=2, channel="signal") is True
