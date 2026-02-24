"""Tests for Obsidian adapter settings resolution."""

from __future__ import annotations

from packages.brain_shared.config import BrainSettings
from resources.adapters.obsidian.config import (
    ObsidianAdapterSettings,
    resolve_obsidian_adapter_settings,
)


def test_resolve_obsidian_adapter_settings_defaults() -> None:
    """Resolver should return defaults when component config is absent."""
    settings = BrainSettings(components={})

    resolved = resolve_obsidian_adapter_settings(settings)

    assert resolved == ObsidianAdapterSettings()


def test_resolve_obsidian_adapter_settings_component_override() -> None:
    """Resolver should hydrate explicit component overrides."""
    settings = BrainSettings(
        components={
            "adapter_obsidian": {
                "base_url": "http://localhost:9999",
                "api_key": "token",
                "timeout_seconds": 3.0,
                "max_retries": 1,
            }
        }
    )

    resolved = resolve_obsidian_adapter_settings(settings)

    assert resolved.base_url == "http://localhost:9999"
    assert resolved.api_key == "token"
    assert resolved.timeout_seconds == 3.0
    assert resolved.max_retries == 1
