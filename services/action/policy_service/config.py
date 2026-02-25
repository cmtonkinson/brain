"""Pydantic settings for Policy Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.policy_service.component import SERVICE_COMPONENT_ID


class PolicyServiceSettings(BaseModel):
    """Policy Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dedupe_window_seconds: int = Field(default=60, ge=0)
    approval_ttl_seconds: int = Field(default=900, gt=0)
    retention_max_rows: int | None = Field(default=None, gt=0)
    retention_max_age_seconds: int | None = Field(default=None, gt=0)


def resolve_policy_service_settings(settings: BrainSettings) -> PolicyServiceSettings:
    """Resolve policy settings from ``components.service_policy_service``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=PolicyServiceSettings,
    )
