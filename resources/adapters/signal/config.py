"""Pydantic settings for the Signal adapter resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.adapters.signal.component import RESOURCE_COMPONENT_ID


class SignalAdapterSettings(BaseModel):
    """Runtime settings for Signal webhook registration HTTP calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "http://signal-api:8080"
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0)


def resolve_signal_adapter_settings(settings: BrainSettings) -> SignalAdapterSettings:
    """Resolve adapter settings from ``components.adapter_signal``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=SignalAdapterSettings,
    )
