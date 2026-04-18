"""Pydantic settings for Ingestion Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.control.ingestion.component import SERVICE_COMPONENT_ID


class IngestionServiceSettings(BaseModel):
    """Ingestion Service runtime behavior settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anchor_folder: str = Field(default="anchors")
    """Vault-relative path prefix for anchor note files."""

    visual_mime_allowlist: tuple[str, ...] = Field(
        default=("image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml")
    )
    """MIME types that are eligible for vault attachment materialization during anchoring."""

    attachments_folder: str = Field(default="attachments")
    """Vault-relative path prefix for materialized visual attachments."""

    max_payload_bytes: int = Field(default=100 * 1024 * 1024, ge=1)
    """Maximum accepted inline payload size in bytes (default: 100 MiB)."""


def resolve_ingestion_service_settings(
    settings: CoreRuntimeSettings,
) -> IngestionServiceSettings:
    """Resolve Ingestion Service settings from ``service.ingestion``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=IngestionServiceSettings,
    )
