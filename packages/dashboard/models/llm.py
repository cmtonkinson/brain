"""LLM view models rendered by the LLM pane."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.dashboard.models.data_source import ProvenanceRecord


class LLMUsageRowView(BaseModel):
    """One provider/model usage row with derived recent-rate pressure fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    request_count: int = Field(ge=0)
    token_count: int = Field(ge=0)
    request_rate_5s: float | None = Field(default=None, ge=0)
    request_rate_60s: float | None = Field(default=None, ge=0)
    request_rate_10m: float | None = Field(default=None, ge=0)
    token_rate_5s: float | None = Field(default=None, ge=0)
    token_rate_60s: float | None = Field(default=None, ge=0)
    token_rate_10m: float | None = Field(default=None, ge=0)
    allowance_requests_per_minute: float | None = Field(default=None, ge=0)
    allowance_tokens_per_minute: float | None = Field(default=None, ge=0)
    headroom_requests_per_minute: float | None = Field(default=None, ge=0)
    headroom_tokens_per_minute: float | None = Field(default=None, ge=0)
    pressure_state: Literal["safe", "projected_breach", "over_limit", "unknown"]
    sampled_at: datetime
    provenance: tuple[ProvenanceRecord, ...] = ()


class LLMUsageTableView(BaseModel):
    """Current render-ready table state for the LLM pane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: tuple[LLMUsageRowView, ...] = ()
