"""Conversation memory and persistence via Obsidian."""

import hashlib
import logging
from datetime import datetime

from config import settings
from models import ConversationMessage
from tools.obsidian import ObsidianClient

logger = logging.getLogger(__name__)


def _normalize_channel(channel: str | None) -> str:
    normalized = (channel or settings.conversation.default_channel or "").strip().lower()
    return normalized or "default"


def get_conversation_path(date: datetime, sender: str, channel: str | None = None) -> str:
    """Generate the Obsidian path for a conversation.

    Args:
        date: The date of the conversation
        sender: The sender's identifier (phone number for Signal)
        channel: Message channel identifier (defaults to configured default)

    Returns:
        Path like "Brain/Conversations/2026/01/signal-2026-01-12-a3f2.md"
    """
    # Create a short hash from sender for privacy
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]
    date_str = date.strftime("%Y-%m-%d")
    year = date.strftime("%Y")
    month = date.strftime("%m")
    channel_slug = _normalize_channel(channel)

    folder = settings.conversation.folder
    return f"{folder}/{year}/{month}/{channel_slug}-{date_str}-{sender_hash}.md"


def get_summary_path(date: datetime, sender: str, channel: str | None = None) -> str:
    """Generate the Obsidian path for a summary note."""
    sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:4]
    date_str = date.strftime("%Y-%m-%d")
    time_str = date.strftime("%H%M%S")
    year = date.strftime("%Y")
    month = date.strftime("%m")
    channel_slug = _normalize_channel(channel)

    folder = settings.conversation.folder
    return (
        f"{folder}/Summaries/{year}/{month}/"
        f"{channel_slug}-summary-{date_str}-{time_str}-{sender_hash}.md"
    )


def create_summary_frontmatter(
    sender: str, timestamp: datetime, conversation_path: str, channel: str | None = None
) -> str:
    """Create YAML frontmatter for a summary note."""
    channel_slug = _normalize_channel(channel)
    return f"""---
type: conversation_summary
channel: {channel_slug}
created: {timestamp.isoformat()}
conversation: {conversation_path}
participants:
  - {sender}
tags:
  - conversation
  - summary
---

# Summary: {timestamp.strftime("%Y-%m-%d %H:%M")}

"""


def create_conversation_frontmatter(
    sender: str, timestamp: datetime, channel: str | None = None
) -> str:
    """Create YAML frontmatter for a new conversation note.

    Args:
        sender: The sender's identifier
        timestamp: When the conversation started
        channel: Message channel identifier (defaults to configured default)

    Returns:
        YAML frontmatter string
    """
    channel_slug = _normalize_channel(channel)
    return f"""---
type: conversation
channel: {channel_slug}
started: {timestamp.isoformat()}
participants:
  - {sender}
tags:
  - conversation
  - brain
---

# Conversation: {timestamp.strftime("%Y-%m-%d")}

"""


class ConversationMemory:
    """Manages conversation persistence in Obsidian."""

    def __init__(self, obsidian_client: ObsidianClient):
        self.obsidian = obsidian_client
        self._conversation_paths: dict[str, str] = {}  # channel+sender -> current path
        self._summary_turn_counts: dict[str, int] = {}  # channel+sender -> turns since last summary

    def _cache_key(self, sender: str, channel: str | None) -> str:
        return f"{_normalize_channel(channel)}::{sender}"

    async def get_or_create_conversation(
        self, sender: str, timestamp: datetime | None = None, channel: str | None = None
    ) -> str:
        """Get the current conversation path, creating the note if needed.

        Args:
            sender: The sender's identifier
            timestamp: Optional timestamp (defaults to now)
            channel: Message channel identifier (defaults to configured default)

        Returns:
            Path to the conversation note in Obsidian
        """
        timestamp = timestamp or datetime.now()
        path = get_conversation_path(timestamp, sender, channel)
        cache_key = self._cache_key(sender, channel)

        # Check cache first
        if cache_key in self._conversation_paths:
            cached_path = self._conversation_paths[cache_key]
            # If same day, return cached path
            if cached_path == path:
                logger.info("Memory conversation reused: %s", path)
                return path

        # Check if note exists
        exists = await self.obsidian.note_exists(path)

        if not exists:
            # Create new conversation note
            frontmatter = create_conversation_frontmatter(sender, timestamp, channel)
            await self.obsidian.create_note(path, frontmatter)
            logger.info("Created new conversation: %s", path)
        else:
            logger.info("Memory conversation exists: %s", path)

        # Update cache
        self._conversation_paths[cache_key] = path
        return path

    async def log_message(
        self,
        sender: str,
        role: str,
        content: str,
        timestamp: datetime | None = None,
        channel: str | None = None,
    ) -> None:
        """Log a message to the conversation.

        Args:
            sender: The sender's identifier (used to find conversation)
            role: "user" or "assistant"
            content: The message content
            timestamp: Optional timestamp (defaults to now)
            channel: Message channel identifier (defaults to configured default)
        """
        timestamp = timestamp or datetime.now()
        path = await self.get_or_create_conversation(sender, timestamp, channel)

        message = ConversationMessage(
            role=role,
            content=content,
            timestamp=timestamp,
        )

        # Append message to note
        markdown = f"\n{message.to_markdown()}"
        await self.obsidian.append_to_note(path, markdown)
        logger.info(
            "Memory log_message role=%s chars=%s path=%s",
            role,
            len(content),
            path,
        )

    async def get_recent_context(
        self, sender: str, max_chars: int = 4000, channel: str | None = None
    ) -> str | None:
        """Get recent conversation context for a sender.

        Args:
            sender: The sender's identifier
            max_chars: Maximum characters to return
            channel: Message channel identifier (defaults to configured default)

        Returns:
            Recent conversation content, or None if no conversation exists
        """
        timestamp = datetime.now()
        path = get_conversation_path(timestamp, sender, channel)

        try:
            content = await self.obsidian.get_note(path)
            # Return last max_chars characters
            if len(content) > max_chars:
                content = content[-max_chars:]
                # Try to start at a message boundary
                newline_pos = content.find("\n## ")
                if newline_pos > 0:
                    content = content[newline_pos:]
            logger.info(
                "Memory recent_context loaded chars=%s path=%s",
                len(content),
                path,
            )
            return content
        except FileNotFoundError:
            logger.info("Memory recent_context missing path=%s", path)
            return None

    async def log_summary(
        self,
        sender: str,
        summary: str,
        timestamp: datetime | None = None,
        channel: str | None = None,
    ) -> str:
        """Create a new summary note and return its path."""
        timestamp = timestamp or datetime.now()
        conversation_path = await self.get_or_create_conversation(sender, timestamp, channel)
        path = get_summary_path(timestamp, sender, channel)
        frontmatter = create_summary_frontmatter(
            sender, timestamp, conversation_path, channel
        )
        content = f"{frontmatter}{summary.strip()}\n"
        await self.obsidian.create_note(path, content)
        logger.info("Created summary note: %s", path)
        return path

    async def log_summary_marker(
        self,
        sender: str,
        summary_path: str,
        timestamp: datetime | None = None,
        channel: str | None = None,
    ) -> None:
        """Append a one-line summary marker to the conversation log."""
        timestamp = timestamp or datetime.now()
        conversation_path = await self.get_or_create_conversation(sender, timestamp, channel)
        marker = f"\n> Summary saved: [[{summary_path}]]\n"
        await self.obsidian.append_to_note(conversation_path, marker)
        logger.info("Summary marker appended: %s", conversation_path)

    def should_write_summary(self, sender: str, interval: int, channel: str | None = None) -> bool:
        """Return True when the sender hits the summary interval."""
        if interval <= 0:
            return False
        cache_key = self._cache_key(sender, channel)
        count = self._summary_turn_counts.get(cache_key, 0) + 1
        self._summary_turn_counts[cache_key] = count
        return count % interval == 0
