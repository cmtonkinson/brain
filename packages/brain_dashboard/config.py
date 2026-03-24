"""Dashboard-local configuration models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DashboardConfig(BaseModel):
    """Runtime configuration for the out-of-band Brain dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app_title: str = Field(default="Brain Dashboard")
    log_follow_enabled: bool = Field(default=True)
    refresh_interval_seconds: float = Field(default=1.0, gt=0)


def load_dashboard_config() -> DashboardConfig:
    """Return the default dashboard configuration."""
    return DashboardConfig()
