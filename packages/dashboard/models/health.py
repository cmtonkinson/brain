"""Health view models for the dashboard header."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    """Health state for a single named component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    state: Literal["ok", "no", "unknown"]
    detail: str | None = None
    checked_at: datetime | None = None
