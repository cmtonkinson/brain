"""Tests for Obsidian substrate settings resolution."""

from __future__ import annotations

from pathlib import Path

from packages.brain_shared.config import load_core_runtime_settings
from resources.substrates.obsidian.config import (
    ObsidianSubstrateSettings,
    resolve_obsidian_substrate_settings,
)


def test_resolve_obsidian_substrate_settings_defaults(tmp_path: Path) -> None:
    """Resolver should return defaults when component config is absent."""
    settings = load_core_runtime_settings(
        core_config_path=tmp_path / "core.yaml",
        resources_config_path=tmp_path / "resources.yaml",
    )

    resolved = resolve_obsidian_substrate_settings(settings)

    assert resolved == ObsidianSubstrateSettings()


def test_resolve_obsidian_substrate_settings_component_override(tmp_path: Path) -> None:
    """Resolver should hydrate explicit component overrides."""
    settings = load_core_runtime_settings(
        core_config_path=tmp_path / "core.yaml",
        resources_config_path=tmp_path / "resources.yaml",
        environ={
            "BRAIN_RESOURCES_SUBSTRATE__OBSIDIAN__BASE_URL": "http://localhost:9999",
            "BRAIN_RESOURCES_SUBSTRATE__OBSIDIAN__API_KEY": "token",
            "BRAIN_RESOURCES_SUBSTRATE__OBSIDIAN__TIMEOUT_SECONDS": "3.0",
            "BRAIN_RESOURCES_SUBSTRATE__OBSIDIAN__MAX_RETRIES": "1",
        },
    )

    resolved = resolve_obsidian_substrate_settings(settings)

    assert resolved.base_url == "http://localhost:9999"
    assert resolved.api_key == "token"
    assert resolved.timeout_seconds == 3.0
    assert resolved.max_retries == 1
