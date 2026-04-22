"""Pydantic settings for Memory Authority Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.state.memory_authority.component import SERVICE_COMPONENT_ID


class MemoryAuthoritySettings(BaseModel):
    """Memory Authority Service runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_turns_to_keep: int = Field(default=10, ge=0)
    max_turns_to_keep: int = Field(default=20, gt=0)
    focus_token_budget: int = Field(default=512, gt=0)
    conversation_episode_idle_seconds: int = Field(default=3600, ge=0)

    def model_post_init(self, __context: object) -> None:
        """Require the moving summary threshold to be >= the retained minimum."""
        if self.max_turns_to_keep < self.min_turns_to_keep:
            raise ValueError("max_turns_to_keep must be >= min_turns_to_keep")


def resolve_memory_authority_settings(
    settings: CoreRuntimeSettings,
) -> MemoryAuthoritySettings:
    """Resolve MAS settings from ``service.memory_authority``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=MemoryAuthoritySettings,
    )
