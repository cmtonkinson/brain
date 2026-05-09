"""Pydantic settings for Relay Service.

Combines the previously-separate Relay inbound (inbound) and Relay outbound
(outbound) settings under a single ``service.relay`` namespace with nested
``inbound``, ``outbound``, and ``identity`` sections.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from lib.shared.config import CoreRuntimeSettings, component_settings_for
from services.effect.relay._outbound.config import RelayOutboundServiceSettings
from services.effect.relay._inbound.config import (
    RelayInboundIdentitySettings,
    RelayInboundServiceSettings,
)


class RelayServiceSettings(BaseModel):
    """Top-level Relay settings composed of inbound/outbound/identity blocks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    inbound: RelayInboundServiceSettings = Field(
        default_factory=RelayInboundServiceSettings
    )
    outbound: RelayOutboundServiceSettings = Field(
        default_factory=RelayOutboundServiceSettings
    )
    identity: RelayInboundIdentitySettings | None = None


def resolve_relay_settings(settings: CoreRuntimeSettings) -> RelayServiceSettings:
    """Resolve the Relay settings block from the canonical `relay` config root."""
    raw = component_settings_for(settings, component_name="relay")

    inbound_raw = raw.get("inbound", {}) or {}
    outbound_raw = raw.get("outbound", {}) or {}
    identity_raw = raw.get("identity", None)

    if identity_raw is None:
        identity = RelayInboundIdentitySettings(
            operator_contact_e164=settings.core.profile.operator.signal_contact_e164,
            default_dial_code=settings.core.profile.default_dial_code,
        )
    else:
        identity = RelayInboundIdentitySettings.model_validate(identity_raw)

    return RelayServiceSettings(
        inbound=RelayInboundServiceSettings.model_validate(inbound_raw),
        outbound=RelayOutboundServiceSettings.model_validate(outbound_raw),
        identity=identity,
    )
