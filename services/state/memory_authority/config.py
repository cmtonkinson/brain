"""Pydantic settings for Memory Authority Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.state.memory_authority.component import SERVICE_COMPONENT_ID
from services.state.memory_authority.domain import BrainVerbosity


class MemoryProfileSettings(BaseModel):
    """Read-only profile values injected into assembled memory context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_name: str = "Operator"
    brain_name: str = "Brain"
    brain_verbosity: BrainVerbosity = BrainVerbosity.NORMAL


class MemoryAuthoritySettings(BaseModel):
    """Memory Authority Service runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dialogue_recent_turns: int = Field(default=10, gt=0)
    dialogue_older_turns: int = Field(default=20, ge=0)
    focus_token_budget: int = Field(default=512, gt=0)
    profile: MemoryProfileSettings = MemoryProfileSettings()


def resolve_memory_authority_settings(
    settings: BrainSettings,
) -> MemoryAuthoritySettings:
    """Resolve MAS settings from ``components.service_memory_authority``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=MemoryAuthoritySettings,
    )
