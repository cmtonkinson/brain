"""Pydantic settings for the Signal adapter resource."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.signal.component import RESOURCE_COMPONENT_ID


class SignalAdapterSettings(BaseModel):
    """Runtime settings for Signal receive, send, and callback forwarding calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str = "http://signal-api:8080"
    receive_e164: str = "+13333333333"
    health_timeout_seconds: float = Field(default=0.5, gt=0)
    receive_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    receive_heartbeat_seconds: float = Field(default=30.0, gt=0)
    send_timeout_seconds: float = Field(default=30.0, gt=0)
    callback_timeout_seconds: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    failure_backoff_initial_seconds: float = Field(default=1.0, gt=0)
    failure_backoff_max_seconds: float = Field(default=30.0, gt=0)
    failure_backoff_multiplier: float = Field(default=2.0, gt=1.0)
    failure_backoff_jitter_ratio: float = Field(default=0.2, ge=0, lt=1.0)

    @field_validator("receive_e164", mode="before")
    @classmethod
    def _validate_receive_e164(cls, value: object) -> object:
        """Require a non-empty receive identity for inbound polling."""
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if normalized == "":
            raise ValueError("receive_e164 must be non-empty")
        return normalized

    @model_validator(mode="after")
    def _validate_timeout_budget(self) -> "SignalAdapterSettings":
        """Require sane timeout relationships for websocket-based receive."""
        if self.receive_heartbeat_seconds <= self.receive_connect_timeout_seconds:
            raise ValueError(
                "receive_heartbeat_seconds must be greater than "
                "receive_connect_timeout_seconds"
            )
        return self


def resolve_signal_adapter_settings(
    settings: CoreRuntimeSettings,
) -> SignalAdapterSettings:
    """Resolve adapter settings from ``adapter.signal``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=SignalAdapterSettings,
    )
