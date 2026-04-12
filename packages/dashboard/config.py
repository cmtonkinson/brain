"""Dashboard-local configuration models."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from packages.dashboard.data_sources.health import HealthConfig
from packages.dashboard.data_sources.postgres import PostgresConnectionConfig


class DataSourcePollConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    poll_seconds: float = Field(default=2.0, gt=0)
    query_timeout_seconds: float = Field(default=5.0, gt=0)
    staleness_threshold_seconds: float = Field(default=10.0, gt=0)


class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    events_recent_seconds: int = Field(default=300, gt=0)
    events_max_items: int = Field(default=5000, gt=0)
    samples_recent_seconds: int = Field(default=600, gt=0)
    samples_max_items: int = Field(default=1200, gt=0)
    snapshots_recent_count: int = Field(default=50, gt=0)


class LogsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    backfill_lines: int = Field(default=200, gt=0)
    buffer_size: int = Field(default=5000, gt=0)
    refresh_seconds: float = Field(default=0.5, gt=0)


class DashboardConfig(BaseModel):
    """Runtime configuration for the out-of-band dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    app_title: str = Field(default="Dashboard")
    log_follow_enabled: bool = Field(default=True)
    refresh_interval_seconds: float = Field(default=1.0, gt=0)
    data_sources: DataSourcePollConfig = Field(default_factory=DataSourcePollConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    health: HealthConfig = Field(default_factory=HealthConfig)
    postgres: PostgresConnectionConfig = Field(
        default_factory=lambda: PostgresConnectionConfig(
            url="postgresql://brain:brain@localhost:8760/brain"
        )
    )


def load_dashboard_config() -> DashboardConfig:
    """Load config from ~/.config/brain/dashboard.yaml if present, else return defaults."""
    import yaml  # type: ignore[import-untyped]

    config_path = Path.home() / ".config" / "brain" / "dashboard.yaml"
    if config_path.exists():
        try:
            data = yaml.safe_load(config_path.read_text())
            if isinstance(data, dict):
                return DashboardConfig.model_validate(data.get("dashboard", data))
        except Exception:
            pass
    return DashboardConfig()
