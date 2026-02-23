"""Pydantic settings for the filesystem adapter component."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.adapters.filesystem.component import RESOURCE_COMPONENT_ID
from resources.adapters.filesystem.validation import normalize_extension


class FilesystemAdapterSettings(BaseModel):
    """Filesystem adapter runtime settings for blob persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root_dir: str = "./var/blobs"
    temp_prefix: str = "blobtmp"
    fsync_writes: bool = True
    default_extension: str = "blob"

    @field_validator("root_dir")
    @classmethod
    def _validate_root_dir(cls, value: str) -> str:
        """Require a non-empty root directory path."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("root_dir is required")
        return normalized

    @field_validator("temp_prefix")
    @classmethod
    def _validate_temp_prefix(cls, value: str) -> str:
        """Require a non-empty temporary filename prefix."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("temp_prefix is required")
        return normalized

    @field_validator("default_extension")
    @classmethod
    def _validate_default_extension(cls, value: str) -> str:
        """Require a normalized non-empty extension token."""
        return normalize_extension(value=value, field_name="default_extension")

    def root_path(self) -> Path:
        """Return the expanded root path for adapter operations."""
        return Path(self.root_dir).expanduser().resolve()


def resolve_filesystem_adapter_settings(
    settings: BrainSettings,
) -> FilesystemAdapterSettings:
    """Resolve filesystem adapter settings from ``components.adapter_filesystem``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=FilesystemAdapterSettings,
    )
