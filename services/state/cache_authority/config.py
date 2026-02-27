"""Pydantic settings for Cache Authority Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.state.cache_authority.component import SERVICE_COMPONENT_ID


class CacheAuthoritySettings(BaseModel):
    """Cache Authority Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key_prefix: str = "brain"
    default_ttl_seconds: int = Field(default=300, gt=0)
    allow_non_expiring_keys: bool = True

    @field_validator("key_prefix", mode="before")
    @classmethod
    def _validate_key_prefix(cls, value: object) -> object:
        """Reject blank key prefixes used for component-scoped key generation."""
        if isinstance(value, str):
            normalized = value.strip()
            if normalized == "":
                raise ValueError("key_prefix must be non-empty")
            return normalized
        return value


def resolve_cache_authority_settings(
    settings: CoreRuntimeSettings,
) -> CacheAuthoritySettings:
    """Resolve CAS settings from ``service.cache_authority``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=CacheAuthoritySettings,
    )
