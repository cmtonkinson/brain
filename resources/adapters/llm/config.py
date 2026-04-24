"""Pydantic settings for the native LLM adapter resource."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lib.shared.config import CoreRuntimeSettings, resolve_component_settings
from resources.adapters.llm.component import RESOURCE_COMPONENT_ID

_VOYAGE_API_BASE = "https://api.voyageai.com"
_OLLAMA_API_BASE = "http://host.docker.internal:11434"
_ANTHROPIC_API_BASE = "https://api.anthropic.com"
_VOYAGE_DEFAULT_OUTPUT_DIMENSION = 2048
_ANTHROPIC_DEFAULT_MAX_TOKENS = 1024


class LlmProviderSettings(BaseModel):
    """Provider-specific backend settings for in-process native LLM calls."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_base: str = ""
    api_key: str = ""
    api_key_env: str = ""
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=0)
    options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_auth_source(self) -> "LlmProviderSettings":
        """Prevent ambiguous inline + env-based API key configuration."""
        if self.api_key.strip() != "" and self.api_key_env.strip() != "":
            raise ValueError("api_key and api_key_env are mutually exclusive")
        return self


class LlmAdapterSettings(BaseModel):
    """In-process native LLM adapter runtime configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    retry_attempts: int = Field(default=2, ge=0)
    retry_initial_delay_seconds: float = Field(default=0.5, ge=0)
    retry_max_delay_seconds: float = Field(default=2.0, gt=0)
    retry_backoff_multiplier: float = Field(default=2.0, gt=1.0)
    retry_jitter_ratio: float = Field(default=0.2, ge=0, lt=1.0)
    providers: dict[str, LlmProviderSettings] = Field(
        default_factory=lambda: {
            "voyage": LlmProviderSettings(
                api_base=_VOYAGE_API_BASE,
                options={"output_dimension": _VOYAGE_DEFAULT_OUTPUT_DIMENSION},
            ),
            "ollama": LlmProviderSettings(
                api_base=_OLLAMA_API_BASE,
            ),
            "anthropic": LlmProviderSettings(
                api_base=_ANTHROPIC_API_BASE,
                options={"max_tokens": _ANTHROPIC_DEFAULT_MAX_TOKENS},
            ),
        }
    )

    @model_validator(mode="after")
    def _validate_provider_keys(self) -> "LlmAdapterSettings":
        """Reject empty provider keys for stable provider lookup semantics."""
        providers = dict(self.providers)
        for provider_name in self.providers:
            if provider_name.strip() == "":
                raise ValueError("providers keys must be non-empty")
            if provider_name == "voyage":
                provider_settings = providers[provider_name]
                updates: dict[str, object] = {}
                if provider_settings.api_base.strip() == "":
                    updates["api_base"] = _VOYAGE_API_BASE
                if "output_dimension" not in provider_settings.options:
                    updates["options"] = {
                        **provider_settings.options,
                        "output_dimension": _VOYAGE_DEFAULT_OUTPUT_DIMENSION,
                    }
                if updates:
                    providers[provider_name] = provider_settings.model_copy(
                        update=updates
                    )
            if provider_name == "ollama":
                provider_settings = providers[provider_name]
                if provider_settings.api_base.strip() == "":
                    providers[provider_name] = provider_settings.model_copy(
                        update={"api_base": _OLLAMA_API_BASE}
                    )
            if provider_name == "anthropic":
                provider_settings = providers[provider_name]
                updates: dict[str, object] = {}
                if provider_settings.api_base.strip() == "":
                    updates["api_base"] = _ANTHROPIC_API_BASE
                if "max_tokens" not in provider_settings.options:
                    updates["options"] = {
                        **provider_settings.options,
                        "max_tokens": _ANTHROPIC_DEFAULT_MAX_TOKENS,
                    }
                if updates:
                    providers[provider_name] = provider_settings.model_copy(
                        update=updates
                    )
        if (
            self.retry_attempts > 0
            and self.retry_max_delay_seconds < self.retry_initial_delay_seconds
        ):
            raise ValueError(
                "retry_max_delay_seconds must be >= "
                "retry_initial_delay_seconds when retries are enabled"
            )
        if providers != self.providers:
            object.__setattr__(self, "providers", providers)
        return self


def resolve_llm_adapter_settings(
    settings: CoreRuntimeSettings,
) -> LlmAdapterSettings:
    """Resolve native LLM adapter settings from ``adapter.llm``."""
    return resolve_component_settings(
        settings=settings,
        component_id=str(RESOURCE_COMPONENT_ID),
        model=LlmAdapterSettings,
    )


def resolve_llm_provider_timeout_seconds(
    *,
    settings: LlmAdapterSettings,
    provider: str,
) -> float:
    """Resolve one provider timeout with adapter-level fallback."""
    provider_config = settings.providers.get(provider)
    if provider_config is None or provider_config.timeout_seconds is None:
        return settings.timeout_seconds
    return provider_config.timeout_seconds


def retry_backoff_schedule_seconds(
    settings: LlmAdapterSettings,
) -> tuple[float, ...]:
    """Return the bounded pre-attempt backoff schedule for timeout retries."""
    delays: list[float] = []
    delay = settings.retry_initial_delay_seconds
    for _ in range(settings.retry_attempts):
        delays.append(min(delay, settings.retry_max_delay_seconds))
        delay *= settings.retry_backoff_multiplier
    return tuple(delays)


def retry_budget_seconds(
    *,
    settings: LlmAdapterSettings,
    provider: str,
    margin_seconds: float = 0.0,
) -> float:
    """Return one full timeout budget for a provider call including retries."""
    timeout_seconds = resolve_llm_provider_timeout_seconds(
        settings=settings,
        provider=provider,
    )
    attempts = 1 + settings.retry_attempts
    return (
        timeout_seconds * attempts
        + sum(retry_backoff_schedule_seconds(settings))
        + max(0.0, margin_seconds)
    )


def max_retry_budget_seconds(
    *,
    settings: LlmAdapterSettings,
    providers: tuple[str, ...],
    margin_seconds: float = 0.0,
) -> float:
    """Return the largest timeout budget across one or more providers."""
    if len(providers) == 0:
        return margin_seconds
    return max(
        retry_budget_seconds(
            settings=settings,
            provider=provider,
            margin_seconds=margin_seconds,
        )
        for provider in providers
    )
