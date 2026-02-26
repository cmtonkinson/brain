"""Tests for Obsidian substrate settings resolution."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import load_settings
from resources.substrates.obsidian.config import (
    ObsidianSubstrateSettings,
    resolve_obsidian_substrate_settings,
)


def test_resolve_obsidian_substrate_settings_defaults(tmp_path: Path) -> None:
    """Resolver should return defaults when component config is absent."""
    settings = load_settings(config_path=tmp_path / "brain.yaml", environ={})

    resolved = resolve_obsidian_substrate_settings(settings)

    assert resolved == ObsidianSubstrateSettings()


def test_resolve_obsidian_substrate_settings_component_override(tmp_path: Path) -> None:
    """Resolver should hydrate explicit component overrides."""
    settings = load_settings(
        cli_params={
            "components": {
                "substrate": {
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

    resolved = resolve_obsidian_substrate_settings(settings)

    assert resolved.base_url == "http://localhost:9999"
    assert resolved.api_key == "token"
    assert resolved.timeout_seconds == 3.0
    assert resolved.max_retries == 1
