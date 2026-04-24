"""Pydantic settings for Vault Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.state.vault.component import SERVICE_COMPONENT_ID


class VaultSettings(BaseModel):
    """Vault runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_list_limit: int = Field(default=500, gt=0)
    max_search_limit: int = Field(default=200, gt=0)


def resolve_vault_settings(
    settings: CoreRuntimeSettings,
) -> VaultSettings:
    """Resolve Vault settings from ``service.vault``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=VaultSettings,
    )
