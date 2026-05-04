"""Shared fixtures for installer + ledger-init tests."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def isolated_install_env(monkeypatch, tmp_path):
    """Hermetic env for installer tests: tmp_path-backed config/state/upgrades."""
    config_dir = tmp_path / "config"
    state_dir = tmp_path / "state"
    cache_dir = tmp_path / "cache"
    upgrades_dir = tmp_path / "upgrades"
    for d in (config_dir, state_dir, cache_dir, upgrades_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BRAIN_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("BRAIN_STATE_DIR", str(state_dir))
    monkeypatch.setenv("BRAIN_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("BRAIN_UPGRADES_DIR", str(upgrades_dir))
    monkeypatch.delenv("BRAIN_UPGRADES_LEDGER", raising=False)

    return {
        "tmp_path": tmp_path,
        "config_dir": config_dir,
        "state_dir": state_dir,
        "cache_dir": cache_dir,
        "upgrades_dir": upgrades_dir,
    }


@pytest.fixture
def make_upgrade_dir(isolated_install_env):
    """Drop a minimal upgrade dir into the fixture upgrades tree."""
    upgrades_dir: Path = isolated_install_env["upgrades_dir"]

    def _make(
        *,
        upgrade_id: str,
        slug: str,
        phase: str = "post-services",
        interactive: bool = False,
        description: str = "fixture upgrade",
    ) -> Path:
        directory = upgrades_dir / f"{upgrade_id}_{slug}"
        directory.mkdir(parents=True, exist_ok=False)
        body = dedent(
            f'''\
            """fixture upgrade {upgrade_id} {slug}."""

            DESCRIPTION = "{description}"
            PHASE = "{phase}"
            INTERACTIVE = {interactive!r}


            def run(ctx):
                pass
            '''
        )
        (directory / "upgrade.py").write_text(body)
        return directory

    return _make
