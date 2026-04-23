"""Global pytest fixtures for repository-wide test isolation."""

from __future__ import annotations

import pytest

from lib.shared.config import ActorSettings, CoreSettings, ResourcesSettings


@pytest.fixture(autouse=True)
def isolate_runtime_config_paths(tmp_path, monkeypatch) -> None:
    """Prevent local ~/.config/brain files from affecting test outcomes."""
    monkeypatch.setattr(CoreSettings, "_config_path", tmp_path / "core.yaml")
    monkeypatch.setattr(ResourcesSettings, "_config_path", tmp_path / "resources.yaml")
    monkeypatch.setattr(ActorSettings, "_config_path", tmp_path / "actors.yaml")
