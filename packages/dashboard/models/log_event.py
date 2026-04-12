"""Structured log event view models rendered by the Log pane."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DashboardLogEvent(BaseModel):
    """One normalized log event for display in the dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: datetime
    level: str
    component: str
    source: str
    message: str
    trace_id: str | None = None
    envelope_id: str | None = None
    raw_payload: Any | None = None
