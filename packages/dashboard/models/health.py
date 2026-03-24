"""Health view models for the dashboard header."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class HealthStatusItem(BaseModel):
    """Compact one-line status entry for a named subsystem."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    status: str = Field(min_length=1)
