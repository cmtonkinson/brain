"""Data source models: Snapshot, History, Viewport, TemporalCursor, ProvenanceRecord."""

from __future__ import annotations

from datetime import datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_type: str
    source_name: str
    source_location: str | None = None
    observed_at: datetime | None = None


class TemporalCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    anchor_time: datetime | None = None
    anchor_id: str | None = None
    anchor_index: int | None = None


class RetentionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    family: Literal["event", "sample", "snapshot"]
    max_items: int | None = None
    recent_seconds: int | None = None
    recent_count: int | None = None


class Snapshot(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: T | None = None
    refreshed_at: datetime | None = None
    error: str | None = None
    stale: bool = False
    provenance: tuple[ProvenanceRecord, ...] = ()


class History(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    records: tuple[T, ...] = ()
    retention: RetentionPolicy
    live_edge_at: datetime | None = None


class Viewport(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: T | None = None
    cursor: TemporalCursor | None = None
    mode: Literal["follow", "frozen"] = "follow"
    live_edge_at: datetime | None = None
    at_live_edge: bool = True
