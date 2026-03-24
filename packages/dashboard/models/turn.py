"""Turn view models rendered by the Turn pane."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TurnView(BaseModel):
    """Current agent-turn snapshot for the selected trace/session."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    inbound_text: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    context_turn_count: int = Field(ge=0)
    summary_count: int = Field(ge=0)
