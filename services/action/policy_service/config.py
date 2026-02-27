"""Pydantic settings for Policy Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.action.policy_service.component import SERVICE_COMPONENT_ID
from services.action.policy_service.domain import (
    PolicyDocument,
    PolicyOverlay,
    PolicyRule,
)


class PolicyServiceSettings(BaseModel):
    """Policy Service runtime behavior and effective-policy bootstrap settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dedupe_window_seconds: int = Field(default=60, ge=0)
    approval_ttl_seconds: int = Field(default=900, gt=0)
    retention_max_rows: int | None = Field(default=None, gt=0)
    retention_max_age_seconds: int | None = Field(default=None, gt=0)
    auto_bind_threshold: float = Field(default=0.90, ge=0.0, le=1.0)
    clarify_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    base_policy: PolicyDocument = Field(
        default_factory=lambda: PolicyDocument(
            policy_id="default", policy_version="1", rules={"*": PolicyRule()}
        )
    )
    overlays: tuple[PolicyOverlay, ...] = ()


def resolve_policy_service_settings(
    settings: CoreRuntimeSettings,
) -> PolicyServiceSettings:
    """Resolve policy settings from ``service.policy_service``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=PolicyServiceSettings,
    )
