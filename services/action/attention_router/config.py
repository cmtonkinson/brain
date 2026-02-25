"""Pydantic settings for Attention Router Service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.attention_router.component import SERVICE_COMPONENT_ID


class AttentionRouterServiceSettings(BaseModel):
    """Runtime settings controlling outbound attention routing behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_channel: str = "signal"
    default_signal_recipient_e164: str = "+10000000000"
    default_signal_sender_e164: str = "+10000000000"
    max_message_chars: int = Field(default=4000, ge=1)
    dedupe_window_seconds: int = Field(default=120, ge=0)
    rate_limit_window_seconds: int = Field(default=60, ge=0)
    rate_limit_max_per_window: int = Field(default=20, ge=1)
    batch_summary_max_items: int = Field(default=5, ge=1)


def resolve_attention_router_service_settings(
    settings: BrainSettings,
) -> AttentionRouterServiceSettings:
    """Resolve service settings from ``components.service_attention_router``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(SERVICE_COMPONENT_ID),
        model=AttentionRouterServiceSettings,
    )
