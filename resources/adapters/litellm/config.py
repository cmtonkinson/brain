"""Pydantic settings for the LiteLLM adapter resource."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.brain_shared.config import CoreRuntimeSettings, resolve_component_settings
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
    timeout_retry_attempts: int = Field(default=2, ge=0)
    timeout_retry_initial_delay_seconds: float = Field(default=0.5, ge=0)
    timeout_retry_max_delay_seconds: float = Field(default=2.0, gt=0)
    timeout_retry_backoff_multiplier: float = Field(default=2.0, gt=1.0)
    timeout_retry_jitter_ratio: float = Field(default=0.2, ge=0, lt=1.0)
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
        if (
            self.timeout_retry_attempts > 0
            and self.timeout_retry_max_delay_seconds
            < self.timeout_retry_initial_delay_seconds
        ):
            raise ValueError(
                "timeout_retry_max_delay_seconds must be >= "
                "timeout_retry_initial_delay_seconds when retries are enabled"
            )
        return self


def resolve_litellm_adapter_settings(
    settings: CoreRuntimeSettings,
) -> LiteLlmAdapterSettings:
    """Resolve LiteLLM adapter settings from ``adapter.litellm``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=LiteLlmAdapterSettings,
    )


def resolve_litellm_provider_timeout_seconds(
    *,
    settings: LiteLlmAdapterSettings,
    provider: str,
) -> float:
    """Resolve one provider timeout with adapter-level fallback."""
    provider_config = settings.providers.get(provider)
    if provider_config is None or provider_config.timeout_seconds is None:
        return settings.timeout_seconds
    return provider_config.timeout_seconds


def timeout_retry_backoff_schedule_seconds(
    settings: LiteLlmAdapterSettings,
) -> tuple[float, ...]:
    """Return the bounded pre-attempt backoff schedule for timeout retries."""
    delays: list[float] = []
    delay = settings.timeout_retry_initial_delay_seconds
    for _ in range(settings.timeout_retry_attempts):
        delays.append(min(delay, settings.timeout_retry_max_delay_seconds))
        delay *= settings.timeout_retry_backoff_multiplier
    return tuple(delays)


def timeout_retry_budget_seconds(
    *,
    settings: LiteLlmAdapterSettings,
    provider: str,
    margin_seconds: float = 0.0,
) -> float:
    """Return one full timeout budget for a provider call including retries."""
    timeout_seconds = resolve_litellm_provider_timeout_seconds(
        settings=settings,
        provider=provider,
    )
    attempts = 1 + settings.timeout_retry_attempts
    return (
        timeout_seconds * attempts
        + sum(timeout_retry_backoff_schedule_seconds(settings))
        + max(0.0, margin_seconds)
    )


def max_timeout_retry_budget_seconds(
    *,
    settings: LiteLlmAdapterSettings,
    providers: tuple[str, ...],
    margin_seconds: float = 0.0,
) -> float:
    """Return the largest timeout budget across one or more providers."""
    if len(providers) == 0:
        return margin_seconds
    return max(
        timeout_retry_budget_seconds(
            settings=settings,
            provider=provider,
            margin_seconds=margin_seconds,
        )
        for provider in providers
    )
