"""Host view models rendered by the Host pane."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from lib.dashboard.models.data_source import ProvenanceRecord


class HostSnapshotView(BaseModel):
    """One normalized snapshot of host pressure and capacity signals."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cpu_percent: float | None = Field(default=None, ge=0)
    memory_percent: float | None = Field(default=None, ge=0)
    load_1m: float | None = Field(default=None, ge=0)
    load_5m: float | None = Field(default=None, ge=0)
    load_15m: float | None = Field(default=None, ge=0)
    disk_percent: float | None = Field(default=None, ge=0)
    io_read_rate_bytes: float | None = Field(default=None, ge=0)
    io_write_rate_bytes: float | None = Field(default=None, ge=0)
    uptime_seconds: int | None = Field(default=None, ge=0)
    battery_percent: float | None = Field(default=None, ge=0)
    battery_charging: bool | None = None
    sampled_at: datetime
    provenance: tuple[ProvenanceRecord, ...] = ()
