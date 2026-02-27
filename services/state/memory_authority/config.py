"""Pydantic settings for Memory Authority Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.state.memory_authority.component import SERVICE_COMPONENT_ID


class MemoryAuthoritySettings(BaseModel):
    """Memory Authority Service runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dialogue_recent_turns: int = Field(default=10, gt=0)
    dialogue_older_turns: int = Field(default=20, ge=0)
    focus_token_budget: int = Field(default=512, gt=0)


def resolve_memory_authority_settings(
    settings: CoreRuntimeSettings,
) -> MemoryAuthoritySettings:
    """Resolve MAS settings from ``service.memory_authority``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=MemoryAuthoritySettings,
    )
