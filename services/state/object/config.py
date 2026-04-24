"""Pydantic settings for Object Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from services.state.object.component import SERVICE_COMPONENT_ID


class ObjectSettings(BaseModel):
    """Object Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest_algorithm: str = "sha256"
    digest_version: str = "b1"
    max_blob_size_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    @field_validator("digest_algorithm")
    @classmethod
    def _validate_digest_algorithm(cls, value: str) -> str:
        """Restrict digest algorithm support to canonical values."""
        normalized = value.strip().lower()
        if normalized != "sha256":
            raise ValueError("digest_algorithm must be 'sha256'")
        return normalized

    @field_validator("digest_version")
    @classmethod
    def _validate_digest_version(cls, value: str) -> str:
        """Require non-empty digest namespace version."""
        normalized = value.strip().lower()
        if normalized == "":
            raise ValueError("digest_version is required")
        return normalized


def resolve_object_settings(
    settings: CoreRuntimeSettings,
) -> ObjectSettings:
    """Resolve Object settings from ``service.object``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=ObjectSettings,
    )
