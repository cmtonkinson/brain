"""Turn view models rendered by the Turn pane."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CurrentTurnView(BaseModel):
    """Current agent-turn snapshot for the selected trace/session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    inbound_text: str
    phase: Literal["pending", "active", "complete"]
    model_name: str
    provider: str
    context_turn_count: int = Field(ge=0)
    summary_count: int = Field(ge=0)
    token_count: int | None = None


class RecentTurnItemView(BaseModel):
    """Summary row for a recently completed turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str
    session_id: str
    inbound_preview: str
    phase: str
    model_name: str
    recorded_at: datetime
