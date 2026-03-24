"""Structured log event view models rendered by the Log pane."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DashboardLogEvent(BaseModel):
    """One normalized log event for display in the dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: str = Field(min_length=1)
    level: str = Field(min_length=1)
    message: str = Field(min_length=1)
