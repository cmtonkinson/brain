"""Tests for Obsidian adapter settings resolution."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import load_settings
from resources.adapters.obsidian.config import (
    ObsidianAdapterSettings,
    resolve_obsidian_adapter_settings,
)


def test_resolve_obsidian_adapter_settings_defaults(tmp_path: Path) -> None:
    """Resolver should return defaults when component config is absent."""
    settings = load_settings(config_path=tmp_path / "brain.yaml", environ={})

    resolved = resolve_obsidian_adapter_settings(settings)

    assert resolved == ObsidianAdapterSettings()


def test_resolve_obsidian_adapter_settings_component_override(tmp_path: Path) -> None:
    """Resolver should hydrate explicit component overrides."""
    settings = load_settings(
        cli_params={
            "components": {
                "adapter": {
                    "obsidian": {
                        "base_url": "http://localhost:9999",
                        "api_key": "token",
                        "timeout_seconds": 3.0,
                        "max_retries": 1,
                    }
                }
            }
        },
        config_path=tmp_path / "brain.yaml",
        environ={},
    )

    resolved = resolve_obsidian_adapter_settings(settings)

    assert resolved.base_url == "http://localhost:9999"
    assert resolved.api_key == "token"
    assert resolved.timeout_seconds == 3.0
    assert resolved.max_retries == 1
