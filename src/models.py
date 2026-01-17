"""Data models for Brain assistant."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

from config import settings

# SQLAlchemy base
Base = declarative_base()


# Database models
class Task(Base):
    """Pending task or reminder."""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    description = Column(Text, nullable=False)
    scheduled_for = Column(DateTime, nullable=True)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)


class ActionLog(Base):
    """Log of actions taken by the agent."""

    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True)
    action_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Conversation(Base):
    """Conversation metadata (full content stored in Obsidian)."""

    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    obsidian_path = Column(String(500), nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_message_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    message_count = Column(Integer, default=0)


class IndexedNote(Base):
    """Indexed note metadata for Qdrant embedding sync."""

    __tablename__ = "indexed_notes"

    id = Column(Integer, primary_key=True)
    path = Column(String(1000), nullable=False)
    collection = Column(String(200), nullable=False)
    content_hash = Column(String(64), nullable=False)
    modified_at = Column(DateTime, nullable=True)
    chunk_count = Column(Integer, nullable=False, default=0)
    last_indexed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class IndexedChunk(Base):
    """Indexed chunk metadata for a note."""

    __tablename__ = "indexed_chunks"

    id = Column(Integer, primary_key=True)
    note_id = Column(Integer, ForeignKey("indexed_notes.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    qdrant_id = Column(String(64), nullable=False)
    chunk_chars = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# Pydantic models for API/validation
class TaskCreate(BaseModel):
    """Create a new task."""

    description: str
    scheduled_for: Optional[datetime] = None


class TaskResponse(BaseModel):
    """Task response."""

    id: int
    description: str
    scheduled_for: Optional[datetime]
    completed: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SignalMessage(BaseModel):
    """Incoming Signal message from Signal API."""

    sender: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_device: int = 1
    expires_in_seconds: int = 0


class ConversationMessage(BaseModel):
    """In-memory representation of a conversation message."""

    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_markdown(self) -> str:
        """Format message as markdown for Obsidian."""
        time_str = self.timestamp.strftime("%H:%M")
        user_display = settings.user.name or "User"
        role_display = user_display if self.role == "user" else "Brain"
        return f"## {time_str} - {role_display}\n\n{self.content}\n"
