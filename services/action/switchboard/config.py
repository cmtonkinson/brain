"""Pydantic settings for Switchboard Service behavior."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from services.action.switchboard.component import SERVICE_COMPONENT_ID


class SwitchboardServiceSettings(BaseModel):
    """Switchboard ingress runtime settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    queue_name: str = "signal_inbound"
    signature_tolerance_seconds: int = Field(default=300, ge=0)
    webhook_bind_host: str = "0.0.0.0"
    webhook_bind_port: int = Field(default=8091, ge=1, le=65535)
    webhook_path: str = "/v1/inbound/signal/webhook"
    webhook_public_base_url: AnyHttpUrl = "http://127.0.0.1:8091"
    webhook_register_max_retries: int = Field(default=8, ge=0)
    webhook_register_retry_delay_seconds: float = Field(default=2.0, gt=0)

    @field_validator("webhook_path", mode="before")
    @classmethod
    def _normalize_webhook_path(cls, value: object) -> object:
        """Normalize callback path to a canonical absolute URL path."""
        if not isinstance(value, str):
            return value
        path = value.strip()
        if path == "":
            raise ValueError("webhook_path must not be empty")
        if not path.startswith("/"):
            path = f"/{path}"
        return path


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
