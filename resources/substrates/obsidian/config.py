"""Pydantic settings for the Obsidian substrate resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.substrates.obsidian.component import RESOURCE_COMPONENT_ID


class ObsidianSubstrateSettings(BaseModel):
    """Runtime settings for Obsidian Local REST API access."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "http://host.docker.internal:27123"
    api_key: str = ""
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


def resolve_obsidian_substrate_settings(
    settings: BrainSettings,
) -> ObsidianSubstrateSettings:
    """Resolve substrate settings from ``components.substrate.obsidian``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=ObsidianSubstrateSettings,
    )
