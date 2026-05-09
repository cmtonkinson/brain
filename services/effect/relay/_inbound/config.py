"""Pydantic settings for Relay inbound submodule."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, component_settings_for


class RelayInboundServiceSettings(BaseModel):
    """Inbound queue runtime settings used by the Relay's inbound submodule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_name: str = "operator_inbound"
    console_response_queue_name: str = "console_outbound"
    callback_register_max_retries: int = Field(default=8, ge=0)
    callback_register_retry_delay_seconds: float = Field(default=2.0, gt=0)


class RelayInboundIdentitySettings(BaseModel):
    """Operator identity settings consumed by the Relay's inbound submodule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator_contact_e164: str
    default_dial_code: str


def resolve_relay_inbound_service_settings(
    settings: CoreRuntimeSettings,
) -> RelayInboundServiceSettings:
    """Resolve inbound settings from `relay.inbound`."""
    relay_raw = component_settings_for(settings, component_name="relay")
    inbound_raw = relay_raw.get("inbound", {}) or {}
    if not isinstance(inbound_raw, dict):
        raise TypeError("relay.inbound must resolve to an object mapping")
    return RelayInboundServiceSettings.model_validate(inbound_raw)


def resolve_relay_inbound_identity_settings(
    settings: CoreRuntimeSettings,
) -> RelayInboundIdentitySettings:
    """Resolve operator identity from `profile` with optional `relay.identity` override."""
    relay_raw = component_settings_for(settings, component_name="relay")
    identity_raw = relay_raw.get("identity", None)
    if isinstance(identity_raw, dict):
        return RelayInboundIdentitySettings.model_validate(identity_raw)
    return RelayInboundIdentitySettings(
        operator_contact_e164=settings.core.profile.operator.signal_contact_e164,
        default_dial_code=settings.core.profile.default_dial_code,
    )
