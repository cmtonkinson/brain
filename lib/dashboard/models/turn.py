"""Turn view models rendered by the Turn pane."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CurrentTurnView(BaseModel):
    """Most recent dialogue exchange rendered in the Turn pane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["pending", "complete"]
    inbound_content: str
    inbound_time: datetime
    inbound_principal: str
    response_content: str | None = None
    response_time: datetime | None = None
    model: str | None = None
    provider: str | None = None
    reasoning_level: str | None = None
    token_count: int | None = None
    trace_id: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)


class RecentTurnItemView(BaseModel):
    """Compact recent-turn row rendered beneath the current exchange."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    direction: Literal["in", "out"]
    summary: str
