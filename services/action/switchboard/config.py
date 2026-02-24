"""Pydantic settings for Switchboard Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.switchboard.component import SERVICE_COMPONENT_ID


class SwitchboardServiceSettings(BaseModel):
    """Switchboard ingress runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_name: str = "signal_inbound"
    signature_tolerance_seconds: int = Field(default=300, ge=0)


class SwitchboardIdentitySettings(BaseModel):
    """Operator and webhook identity settings consumed by Switchboard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_signal_e164: str
    default_country_code: str
    webhook_shared_secret: str


def resolve_switchboard_service_settings(
    settings: BrainSettings,
) -> SwitchboardServiceSettings:
    """Resolve service settings from ``components.service_switchboard``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=SwitchboardServiceSettings,
    )


def resolve_switchboard_identity_settings(
    settings: BrainSettings,
) -> SwitchboardIdentitySettings:
    """Resolve operator identity + webhook secret settings from root profile."""
    return SwitchboardIdentitySettings(
        operator_signal_e164=settings.profile.operator.signal_e164,
        default_country_code=settings.profile.default_country_code,
        webhook_shared_secret=settings.profile.webhook_shared_secret,
    )
