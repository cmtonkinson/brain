"""Pydantic settings for Vault Authority Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.state.vault_authority.component import SERVICE_COMPONENT_ID


class VaultAuthoritySettings(BaseModel):
    """Vault Authority runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_list_limit: int = Field(default=500, gt=0)
    max_search_limit: int = Field(default=200, gt=0)


def resolve_vault_authority_settings(settings: BrainSettings) -> VaultAuthoritySettings:
    """Resolve VAS settings from ``components.service_vault_authority``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=VaultAuthoritySettings,
    )
