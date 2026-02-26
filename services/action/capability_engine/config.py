"""Pydantic settings for Capability Engine Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.capability_engine.component import SERVICE_COMPONENT_ID


class CapabilityEngineSettings(BaseModel):
    """Capability Engine runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    discovery_root: str = "capabilities"
    default_max_autonomy: int = Field(default=0, ge=0)


def resolve_capability_engine_settings(
    settings: BrainSettings,
) -> CapabilityEngineSettings:
    """Resolve CES settings from ``components.service.capability_engine``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=CapabilityEngineSettings,
    )
