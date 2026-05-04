"""Test fixtures for the upgrades subsystem."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from textwrap import dedent

import pytest

from lib.core.upgrades.api import UpgradeContext


@pytest.fixture
def isolated_state_env(monkeypatch, tmp_path):
    """Point BRAIN_* env at tmp_path-backed dirs so the runner is hermetic."""
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
def upgrade_context(tmp_path) -> UpgradeContext:
    """Synthesize an UpgradeContext rooted at tmp_path for unit tests."""
    config = tmp_path / "config"
    state = tmp_path / "state"
    cache = tmp_path / "cache"
    log = tmp_path / "logs"
    for d in (config, state, cache, log):
        d.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("brain.upgrade.test")
    return UpgradeContext(
        upgrade_id="00000000_0000",
        slug="test_fixture",
        phase="post-services",
        interactive=False,
        repo_root=tmp_path,
        config_dir=config,
        state_dir=state,
        cache_dir=cache,
        log_dir=log,
        logger=logger,
    )


@pytest.fixture
def make_upgrade(isolated_state_env) -> Callable[..., Path]:
    """Factory that writes a minimal upgrade dir and returns its path."""
    upgrades_dir: Path = isolated_state_env["upgrades_dir"]

    def _make(
        *,
        upgrade_id: str,
        slug: str,
        body: str = "    pass\n",
        description: str = "fixture upgrade",
        phase: str = "post-services",
        interactive: bool = False,
        timeout_seconds: int | None = None,
        also_test: bool = False,
    ) -> Path:
        directory = upgrades_dir / f"{upgrade_id}_{slug}"
        directory.mkdir(parents=True, exist_ok=False)
        timeout_line = (
            f"TIMEOUT_SECONDS = {timeout_seconds}\n"
            if timeout_seconds is not None
            else ""
        )
        contents = (
            dedent(
                f'''\
            """fixture upgrade {upgrade_id} {slug}."""

            from __future__ import annotations

            from lib.core.upgrades.api import UpgradeContext

            DESCRIPTION = "{description}"
            PHASE = "{phase}"
            INTERACTIVE = {interactive!r}
            {timeout_line}

            def run(ctx: UpgradeContext) -> None:
            '''
            )
            + body
        )
        (directory / "upgrade.py").write_text(contents)
        if also_test:
            (directory / "test_upgrade.py").write_text(
                "def test_smoke(): assert True\n"
            )
        return directory

    return _make
