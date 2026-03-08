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
    resolve_litellm_adapter_settings,
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
    assert resolved.providers == {
        "ollama": LiteLlmProviderSettings(api_base="http://host.docker.internal:11434"),
        "openai": LiteLlmProviderSettings(
            api_key_env="OPENAI_API_KEY",
            timeout_seconds=7.5,
            max_retries=4,
        ),
    }
