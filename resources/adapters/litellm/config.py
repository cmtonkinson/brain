"""Pydantic settings for the LiteLLM adapter resource."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.brain_shared.config import BrainSettings, resolve_component_settings
from resources.adapters.litellm.component import RESOURCE_COMPONENT_ID


class LiteLlmProviderSettings(BaseModel):
    """Provider-specific backend settings for in-process LiteLLM calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_base: str = ""
    api_key: str = ""
    api_key_env: str = ""
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_auth_source(self) -> "LiteLlmProviderSettings":
        """Prevent ambiguous inline + env-based API key configuration."""
        if self.api_key.strip() != "" and self.api_key_env.strip() != "":
            raise ValueError("api_key and api_key_env are mutually exclusive")
        return self


class LiteLlmAdapterSettings(BaseModel):
    """In-process LiteLLM adapter runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    providers: dict[str, LiteLlmProviderSettings] = Field(
        default_factory=lambda: {
            "ollama": LiteLlmProviderSettings(
                api_base="http://host.docker.internal:11434"
            )
        }
    )

    @model_validator(mode="after")
    def _validate_provider_keys(self) -> "LiteLlmAdapterSettings":
        """Reject empty provider keys for stable provider lookup semantics."""
        for provider_name in self.providers:
            if provider_name.strip() == "":
                raise ValueError("providers keys must be non-empty")
        return self


def resolve_litellm_adapter_settings(settings: BrainSettings) -> LiteLlmAdapterSettings:
    """Resolve LiteLLM adapter settings from ``components.adapter.litellm``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=LiteLlmAdapterSettings,
    )
