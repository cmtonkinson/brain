"""Pydantic settings for the Obsidian adapter resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.adapters.obsidian.component import RESOURCE_COMPONENT_ID


class ObsidianAdapterSettings(BaseModel):
    """Runtime settings for Obsidian Local REST API access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "http://127.0.0.1:27124"
    api_key: str = ""
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


def resolve_obsidian_adapter_settings(
    settings: BrainSettings,
) -> ObsidianAdapterSettings:
    """Resolve adapter settings from ``components.adapter_obsidian``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=ObsidianAdapterSettings,
    )
