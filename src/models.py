"""Data models for Brain assistant."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base

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
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class ActionLog(Base):
    """Log of actions taken by the agent."""
    
    __tablename__ = "action_logs"
    
    id = Column(Integer, primary_key=True)
    action_type = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    result = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class Conversation(Base):
    """Conversation metadata (full content stored in Obsidian)."""
    
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True)
    obsidian_path = Column(String(500), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow)
    last_message_at = Column(DateTime, default=datetime.utcnow)
    message_count = Column(Integer, default=0)


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
    
    class Config:
        from_attributes = True


class SignalMessage(BaseModel):
    """Incoming Signal message."""
    
    sender: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
