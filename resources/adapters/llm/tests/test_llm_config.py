"""Tests for native LLM adapter settings resolution."""

from __future__ import annotations

from lib.shared.config import (
    CoreRuntimeSettings,
    CoreSettings,
    ResourcesSettings,
)
from resources.adapters.llm.config import (
    LlmAdapterSettings,
    LlmProviderSettings,
    max_retry_budget_seconds,
    resolve_llm_adapter_settings,
    retry_backoff_schedule_seconds,
)


def test_resolve_llm_adapter_settings_defaults() -> None:
    """Resolver should return model defaults when component section is absent."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
    )

    resolved = resolve_llm_adapter_settings(settings)

    assert resolved == LlmAdapterSettings()


def test_resolve_llm_adapter_settings_component_override() -> None:
    """Resolver should deep-merge component overrides onto model defaults."""
    settings = CoreRuntimeSettings(
        core=CoreSettings.model_validate({}),
        resources=ResourcesSettings.model_validate({}),
        component_settings={
            "llm": {
                "timeout_seconds": 5.5,
                "max_retries": 1,
                "providers": {
                    "openai": {
                        "api_key_env": "OPENAI_API_KEY",
                        "timeout_seconds": 7.5,
                        "max_retries": 4,
                    }
                },
            }
        },
    )

    resolved = resolve_llm_adapter_settings(settings)

    assert resolved.timeout_seconds == 5.5
    assert resolved.max_retries == 1
    assert resolved.retry_attempts == 2
    assert resolved.providers == {
        "voyage": LlmProviderSettings(
            api_base="https://api.voyageai.com",
            options={"output_dimension": 2048},
        ),
        "ollama": LlmProviderSettings(
            api_base="http://host.docker.internal:11434",
        ),
        "anthropic": LlmProviderSettings(
            api_base="https://api.anthropic.com",
            options={"max_tokens": 1024},
        ),
        "openai": LlmProviderSettings(
            api_key_env="OPENAI_API_KEY",
            timeout_seconds=7.5,
            max_retries=4,
        ),
    }


def test_retry_budget_helpers_reflect_backoff_and_margin() -> None:
    """Retry budget helpers should include retries, backoff, and margin."""
    settings = LlmAdapterSettings(
        timeout_seconds=10.0,
        retry_attempts=2,
        retry_initial_delay_seconds=0.5,
        retry_max_delay_seconds=2.0,
        retry_backoff_multiplier=2.0,
        providers={
            "anthropic": LlmProviderSettings(timeout_seconds=12.0),
        },
    )

    assert retry_backoff_schedule_seconds(settings) == (0.5, 1.0)
    assert (
        max_retry_budget_seconds(
            settings=settings,
            providers=("anthropic",),
            margin_seconds=2.0,
        )
        == 39.5
    )
