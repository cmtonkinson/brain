"""Pydantic settings for Switchboard Service behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from services.action.switchboard.component import SERVICE_COMPONENT_ID


class SwitchboardServiceSettings(BaseModel):
    """Switchboard inbound-queue runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_name: str = "signal_inbound"
    console_queue_name: str = "console_inbound"
    console_response_queue_name: str = "console_outbound"
    callback_register_max_retries: int = Field(default=8, ge=0)
    callback_register_retry_delay_seconds: float = Field(default=2.0, gt=0)


class SwitchboardIdentitySettings(BaseModel):
    """Operator identity settings consumed by Switchboard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_signal_contact_e164: str
    default_dial_code: str


def resolve_switchboard_service_settings(
    settings: CoreRuntimeSettings,
) -> SwitchboardServiceSettings:
    """Resolve service settings from ``service.switchboard``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=SwitchboardServiceSettings,
    )


def resolve_switchboard_identity_settings(
    settings: CoreRuntimeSettings,
) -> SwitchboardIdentitySettings:
    """Resolve operator identity settings from root profile."""
    return SwitchboardIdentitySettings(
        operator_signal_contact_e164=settings.core.profile.operator.signal_contact_e164,
        default_dial_code=settings.core.profile.default_dial_code,
    )
