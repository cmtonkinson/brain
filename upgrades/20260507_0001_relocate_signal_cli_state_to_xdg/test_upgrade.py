"""Tests for upgrade 20260507_0001 relocate_signal_cli_state_to_xdg."""

from __future__ import annotations

from pathlib import Path

from lib.core.upgrades.api import UpgradeContext, load_sibling


def _make_ctx(tmp_path: Path) -> UpgradeContext:
    """Build a minimal UpgradeContext rooted under *tmp_path*."""
    import logging

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return UpgradeContext(
        upgrade_id="20260507_0001",
        slug="relocate_signal_cli_state_to_xdg",
        phase="pre-services",
        interactive=False,
        repo_root=repo_root,
        config_dir=tmp_path / "config",
        state_dir=state_dir,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "log",
        logger=logging.getLogger("test"),
    )


def _seed_legacy(ctx: UpgradeContext) -> Path:
    """Create a minimal legacy signal-cli directory with account data."""
    legacy = ctx.repo_root / "data" / "signal-cli"
    data_dir = legacy / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "accounts.json").write_text('{"accounts": []}')
    (data_dir / "707567").write_text("key-material")
    (legacy / "jsonrpc2.yml").write_text("mode: json-rpc")
    return legacy


def _seed_env(ctx: UpgradeContext, value: str = "./data/signal-cli") -> Path:
    """Write a minimal .env file with SIGNAL_CLI_CONFIG_DIR."""
    env_path = ctx.repo_root / ".env"
    env_path.write_text(f"SOME_OTHER=val\nSIGNAL_CLI_CONFIG_DIR={value}\n")
    return env_path


def test_migrates_data_and_updates_env(tmp_path):
    ctx = _make_ctx(tmp_path)
    _seed_legacy(ctx)
    env_path = _seed_env(ctx)

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    target = ctx.state_dir / "signal-cli"
    assert (target / "data" / "accounts.json").exists()
    assert (target / "data" / "707567").exists()
    assert (target / "jsonrpc2.yml").exists()

    content = env_path.read_text()
    assert "SIGNAL_CLI_CONFIG_DIR=" in content
    assert "./data/signal-cli" not in content


def test_skips_when_no_legacy_dir(tmp_path):
    ctx = _make_ctx(tmp_path)
    env_path = _seed_env(ctx)

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    target = ctx.state_dir / "signal-cli"
    assert not target.exists()
    # .env should still be updated (env update is independent of data migration)
    content = env_path.read_text()
    assert "./data/signal-cli" not in content


def test_skips_data_when_no_accounts(tmp_path):
    ctx = _make_ctx(tmp_path)
    legacy = ctx.repo_root / "data" / "signal-cli"
    legacy.mkdir(parents=True)
    (legacy / "jsonrpc2.yml").write_text("mode: json-rpc")
    _seed_env(ctx)

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    target = ctx.state_dir / "signal-cli"
    assert not (target / "data" / "accounts.json").exists()


def test_skips_data_when_target_already_populated(tmp_path):
    ctx = _make_ctx(tmp_path)
    _seed_legacy(ctx)
    target = ctx.state_dir / "signal-cli" / "data"
    target.mkdir(parents=True)
    (target / "accounts.json").write_text('{"existing": true}')
    _seed_env(ctx)

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    # Should not overwrite existing data.
    content = (target / "accounts.json").read_text()
    assert "existing" in content


def test_no_env_file(tmp_path):
    ctx = _make_ctx(tmp_path)
    _seed_legacy(ctx)

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    # Data still migrates even without .env.
    target = ctx.state_dir / "signal-cli"
    assert (target / "data" / "accounts.json").exists()


def test_env_already_set_to_target(tmp_path):
    ctx = _make_ctx(tmp_path)
    target = ctx.state_dir / "signal-cli"
    home = Path.home()
    try:
        relative = target.relative_to(home)
        xdg_value = f"${{HOME}}/{relative}"
    except ValueError:
        xdg_value = str(target)
    env_path = _seed_env(ctx, value=xdg_value)
    original = env_path.read_text()

    upgrade = load_sibling(__file__, "upgrade")
    upgrade.run(ctx)

    assert env_path.read_text() == original
