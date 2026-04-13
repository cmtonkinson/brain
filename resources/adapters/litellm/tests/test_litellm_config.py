"""Tests for LiteLLM adapter settings resolution."""

from __future__ import annotations

from packages.brain_shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from resources.adapters.litellm.config import (
    LiteLlmAdapterSettings,
    LiteLlmProviderSettings,
    max_timeout_retry_budget_seconds,
    resolve_litellm_adapter_settings,
    timeout_retry_backoff_schedule_seconds,
)


def test_resolve_litellm_adapter_settings_defaults() -> None:
    """Resolver should return model defaults when component section is absent."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
    )

    resolved = resolve_litellm_adapter_settings(settings)

    assert resolved == LiteLlmAdapterSettings()


def test_resolve_litellm_adapter_settings_component_override() -> None:
    """Resolver should deep-merge component overrides onto model defaults."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate(
            {
                "adapter": {
                    "litellm": {
                        "timeout_seconds": 5.5,
                        "max_retries": 1,
                        "providers": {
                            "openai": {
                                "api_key_env": "OPENAI_API_KEY",
                                "timeout_seconds": 7.5,
                                "max_retries": 4,
                            }
                        },
                    },
                }
            }
        ),
    )

    resolved = resolve_litellm_adapter_settings(settings)

    assert resolved.timeout_seconds == 5.5
    assert resolved.max_retries == 1
    assert resolved.timeout_retry_attempts == 2
    assert resolved.providers == {
        "ollama": LiteLlmProviderSettings(api_base="http://host.docker.internal:11434"),
        "openai": LiteLlmProviderSettings(
            api_key_env="OPENAI_API_KEY",
            timeout_seconds=7.5,
            max_retries=4,
        ),
    }


def test_timeout_retry_budget_helpers_reflect_backoff_and_margin() -> None:
    """Timeout budget helpers should include retries, backoff, and margin."""
    settings = LiteLlmAdapterSettings(
        timeout_seconds=10.0,
        timeout_retry_attempts=2,
        timeout_retry_initial_delay_seconds=0.5,
        timeout_retry_max_delay_seconds=2.0,
        timeout_retry_backoff_multiplier=2.0,
        providers={
            "anthropic": LiteLlmProviderSettings(timeout_seconds=12.0),
        },
    )

    assert timeout_retry_backoff_schedule_seconds(settings) == (0.5, 1.0)
    assert (
        max_timeout_retry_budget_seconds(
            settings=settings,
            providers=("anthropic",),
            margin_seconds=2.0,
        )
        == 39.5
    )
