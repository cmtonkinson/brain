"""Unit tests for conversation and summary path helpers."""

import hashlib
from datetime import datetime

from config import settings
from tools.memory import get_conversation_path, get_summary_path


def test_get_conversation_path_uses_hash_and_date(monkeypatch) -> None:
    """Conversation paths include sender hash and date."""
    monkeypatch.setattr(settings.obsidian, "root_folder", "_brain", raising=False)
    monkeypatch.setattr(settings.obsidian, "conversation_folder", "conversations", raising=False)
    monkeypatch.setattr(settings.conversation, "default_channel", "signal", raising=False)
    sender = "sender-id"
    timestamp = datetime(2026, 1, 12, 15, 30, 45)
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]

    expected = f"_brain/conversations/2026/01/signal-2026-01-12-{sender_hash}.md"
    assert get_conversation_path(timestamp, sender, channel="signal") == expected


def test_get_summary_path_uses_hash_and_time(monkeypatch) -> None:
    """Summary paths include sender hash and time."""
    monkeypatch.setattr(settings.obsidian, "root_folder", "_brain", raising=False)
    monkeypatch.setattr(settings.obsidian, "conversation_folder", "conversations", raising=False)
    monkeypatch.setattr(settings.obsidian, "summary_folder", "summaries", raising=False)
    monkeypatch.setattr(settings.conversation, "default_channel", "signal", raising=False)
    sender = "sender-id"
    timestamp = datetime(2026, 1, 12, 15, 30, 45)
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]
    time_str = timestamp.strftime("%H%M%S")

    expected = (
        f"_brain/conversations/summaries/2026/01/"
        f"signal-summary-2026-01-12-{time_str}-{sender_hash}.md"
    )
    assert get_summary_path(timestamp, sender, channel="signal") == expected


def test_get_conversation_path_uses_channel_prefix(monkeypatch) -> None:
    """Conversation paths include the channel prefix."""
    monkeypatch.setattr(settings.obsidian, "root_folder", "_brain", raising=False)
    monkeypatch.setattr(settings.obsidian, "conversation_folder", "conversations", raising=False)
    monkeypatch.setattr(settings.conversation, "default_channel", "signal", raising=False)
    sender = "sender-id"
    timestamp = datetime(2026, 2, 3, 10, 0, 0)
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]

    expected = f"_brain/conversations/2026/02/email-2026-02-03-{sender_hash}.md"
    assert get_conversation_path(timestamp, sender, channel="email") == expected
