"""Pydantic settings for the SeaweedFS substrate component."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from lib.shared.blob_validation import normalize_extension
from resources.substrates.seaweedfs.component import RESOURCE_COMPONENT_ID


class SeaweedFSSubstrateSettings(BaseModel):
    """SeaweedFS S3-compatible substrate runtime settings for blob persistence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    endpoint_url: str = "http://seaweedfs:8333"
    bucket: str = "brain-oas"
    region: str = "us-east-1"
    access_key_id: str
    secret_access_key: str
    key_prefix: str = "objects"
    request_timeout_seconds: float = Field(default=10.0, gt=0)
    default_extension: str = "blob"

    @field_validator("endpoint_url")
    @classmethod
    def _validate_endpoint_url(cls, value: str) -> str:
        """Require a non-empty SeaweedFS S3 endpoint URL."""
        normalized = value.strip().rstrip("/")
        if normalized == "":
            raise ValueError("endpoint_url is required")
        return normalized

    @field_validator("bucket")
    @classmethod
    def _validate_bucket(cls, value: str) -> str:
        """Require a non-empty S3 bucket name."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("bucket is required")
        return normalized

    @field_validator("region", "access_key_id", "secret_access_key")
    @classmethod
    def _validate_required_string(cls, value: str) -> str:
        """Require non-empty string settings for S3 client identity."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("value is required")
        return normalized

    @field_validator("key_prefix")
    @classmethod
    def _validate_key_prefix(cls, value: str) -> str:
        """Normalize an optional object-key prefix."""
        return value.strip().strip("/")

    @field_validator("default_extension")
    @classmethod
    def _validate_default_extension(cls, value: str) -> str:
        """Require a normalized non-empty extension token."""
        return normalize_extension(value=value, field_name="default_extension")


def resolve_seaweedfs_substrate_settings(
    settings: CoreRuntimeSettings,
) -> SeaweedFSSubstrateSettings:
    """Resolve SeaweedFS substrate settings from ``substrate.seaweedfs``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=SeaweedFSSubstrateSettings,
    )
