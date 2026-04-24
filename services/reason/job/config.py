"""Pydantic settings for Job Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.reason.job.component import SERVICE_COMPONENT_ID
from services.reason.job.domain import BackoffStrategy


class JobServiceSettings(BaseModel):
    """Job Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_max_attempts: int = Field(default=3, ge=1)
    default_backoff_strategy: BackoffStrategy = BackoffStrategy.exponential
    default_backoff_base_seconds: int = Field(default=60, ge=0)
    orphan_grace_period_hours: int = Field(default=24, ge=1)
    consecutive_failure_threshold: int = Field(default=3, ge=1)
    ignored_pause_age_days: int = Field(default=30, ge=1)
    stalled_execution_threshold_minutes: int = Field(default=60, ge=1)
    retry_batch_size: int = Field(default=100, ge=1)
    provider_poll_interval_seconds: float = Field(default=15.0, gt=0)


def resolve_job_service_settings(
    settings: CoreRuntimeSettings,
) -> JobServiceSettings:
    """Resolve Job Service settings from ``service.job``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=JobServiceSettings,
    )
