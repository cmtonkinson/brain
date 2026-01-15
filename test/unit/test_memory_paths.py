import hashlib
from datetime import datetime

from config import settings
from tools.memory import get_conversation_path, get_summary_path


def test_get_conversation_path_uses_hash_and_date(monkeypatch) -> None:
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    sender = "sender-id"
    timestamp = datetime(2026, 1, 12, 15, 30, 45)
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]

    expected = f"Brain/Conversations/2026/01/signal-2026-01-12-{sender_hash}.md"
    assert get_conversation_path(timestamp, sender) == expected


def test_get_summary_path_uses_hash_and_time(monkeypatch) -> None:
    monkeypatch.setattr(settings.conversation, "folder", "Brain/Conversations", raising=False)
    sender = "sender-id"
    timestamp = datetime(2026, 1, 12, 15, 30, 45)
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]
    time_str = timestamp.strftime("%H%M%S")

    expected = (
        f"Brain/Conversations/Summaries/2026/01/"
        f"signal-summary-2026-01-12-{time_str}-{sender_hash}.md"
    )
    assert get_summary_path(timestamp, sender) == expected
