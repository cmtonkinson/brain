"""Pydantic settings for Relay outbound submodule."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, component_settings_for


class RelayOutboundServiceSettings(BaseModel):
    """Outbound notification routing settings used by the Relay's outbound submodule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_channel: str = "signal"
    approval_channels: tuple[str, ...] = ("signal", "console")
    conversational_channels: tuple[str, ...] = ("signal", "console")
    max_message_chars: int = Field(default=4000, ge=1)
    dedupe_window_seconds: int = Field(default=120, ge=0)
    rate_limit_window_seconds: int = Field(default=60, ge=0)
    rate_limit_max_per_window: int = Field(default=20, ge=1)
    batch_summary_max_items: int = Field(default=5, ge=1)


def resolve_relay_outbound_service_settings(
    settings: CoreRuntimeSettings,
) -> RelayOutboundServiceSettings:
    """Resolve outbound settings from `relay.outbound`."""
    relay_raw = component_settings_for(settings, component_name="relay")
    outbound_raw = relay_raw.get("outbound", {}) or {}
    if not isinstance(outbound_raw, dict):
        raise TypeError("relay.outbound must resolve to an object mapping")
    return RelayOutboundServiceSettings.model_validate(outbound_raw)
